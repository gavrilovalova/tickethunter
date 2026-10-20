from datetime import date, datetime
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from .models import ParseError, Session, ShowSnapshot, Status

BUY_BTN_SELECTOR = "a.js-buy-tickets-btn"
BUY_PATH = "/tickets/buy/"
SOLD_OUT_WORD = "закончились"
STAGE_WORDS = ("сцена", "зал", "арт-кафе", "амфитеатр")
HEADINGS = ["h1", "h2", "h3", "h4", "h5"]


def _preceding_stage_heading(el) -> str:
    h = el.find_previous(HEADINGS)
    while h is not None:
        t = h.get_text(strip=True)
        if t and any(w in t.lower() for w in STAGE_WORDS):
            return t
        h = h.find_previous(HEADINGS)
    return ""


def _parse_datetime(raw: str) -> str:
    """'2026-12-26-19-00-00' -> '2026-12-26T19:00'; ValueError if malformed
    (в т.ч. календарно невозможная дата вроде 2026-02-30)."""
    return datetime.strptime(raw, "%Y-%m-%d-%H-%M-%S").strftime("%Y-%m-%dT%H:%M")


def _title(soup: BeautifulSoup) -> str:
    # на странице много h1: первый — логотип сайта, дальше название спектакля и пресса
    for h1 in soup.find_all("h1"):
        if "site-logo" not in (h1.get("class") or []):
            t = h1.get_text(strip=True)
            if t:
                return t
            break
    og = soup.find("meta", attrs={"property": "og:title"})
    return (og.get("content") or "").strip() if og else ""


def parse_show_page(html: str, url: str, today: date) -> ShowSnapshot:
    # `today` оставлен в сигнатуре для вызывающего кода, но больше не используется:
    # сайт отдаёт полную дату в data-datetime, выводить год не нужно.
    soup = BeautifulSoup(html, "html.parser")

    title = _title(soup)
    if not title:
        raise ParseError(f"не найден заголовок спектакля: {url}")

    sessions: dict[str, Session] = {}
    for a in soup.select(BUY_BTN_SELECTOR):
        stage = (a.get("data-stage") or "").strip()
        raw_dt = (a.get("data-datetime") or "").strip()
        if not stage or not raw_dt:
            continue
        try:
            dt = _parse_datetime(raw_dt)
        except ValueError:
            continue                                   # битая дата — пропускаем

        sold_out = ("disabled" in (a.get("class") or [])
                    or SOLD_OUT_WORD in a.get_text(strip=True).lower())
        buy_url = None
        if not sold_out:
            href = a.get("href") or ""
            if BUY_PATH in href:
                buy_url = urljoin(url, href)
            else:
                buy_url = urljoin(url, f"{BUY_PATH}?stageuid={stage}&datetime={raw_dt}")

        s = Session(stage=stage, stage_title=_preceding_stage_heading(a), dt=dt,
                    status=Status.SOLD_OUT if sold_out else Status.AVAILABLE,
                    buy_url=buy_url)
        sessions[s.key] = s

    if not sessions:
        raise ParseError(f"не найдено ни одного сеанса: {url}")
    return ShowSnapshot(title=title, url=url, sessions=list(sessions.values()))
