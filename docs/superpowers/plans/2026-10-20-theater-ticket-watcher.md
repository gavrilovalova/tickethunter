# Theater Ticket Watcher — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Личный Telegram-бот, который по cron в GitHub Actions следит за страницами спектаклей vakhtangov.ru и шлёт Кате уведомление со ссылкой на покупку, когда появились билеты или новая дата.

**Architecture:** Один Python-пакет `watcher/`, запускаемый раз в 5 минут workflow'ом GitHub Actions. Запуск: забрать команды из Telegram (`getUpdates`) → проверить подписки (httpx + BeautifulSoup) → по diff'у состояний разослать уведомления → закоммитить `state.json` обратно в репо. Постоянного сервера нет.

**Tech Stack:** Python 3.12, httpx, beautifulsoup4, pytest, GitHub Actions.

**Spec:** `docs/superpowers/specs/2026-10-20-theater-ticket-watcher-design.md`

## Global Constraints

- Python 3.12; зависимости только `httpx`, `beautifulsoup4` (+ `pytest` для тестов).
- Все тексты бота — по-русски.
- HTTP к сайту театра: таймаут 20 с, User-Agent обычного браузера, `follow_redirects=True`.
- Время сеансов — наивные ISO-строки по московскому времени, формат `YYYY-MM-DDTHH:MM`.
- `state.json` — UTF-8, `ensure_ascii=False`, `indent=2`, `sort_keys=True`, завершающий `\n` (стабильные диффы в git).
- Cron: `*/5 * * * *`; workflow с `concurrency.group: watch`.
- Секреты только из env: `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`. Никаких токенов в коде/репо.
- Сообщения Telegram: `parse_mode=HTML`, пользовательские строки экранируются `html.escape`.

## Review Focus

Проверено против спека; эти случаи не были покрыты задачами изначально — каждому добавлен тест в задачу-владельца:

1. Buy-ссылка без `stageuid`/`datetime` или с кривым `datetime` (например, ссылка «все билеты» или чужой блок) — парсер молча пропускает её, а не роняет весь запуск. → тест в Task 4.
2. Переход через Новый год: «5 января» на странице в октябре — это следующий год, а не прошедшая дата, которую вычистят. → тест в Task 4.
3. Отправка уведомления упала после ретрая — статус сеанса не фиксируется, уведомление повторяется в следующем цикле (не теряется навсегда). → тест в Task 8.
4. Сообщение/кнопка от чужого chat_id — игнорируется молча, состояние не меняется. → тест в Task 7.
5. Та же ссылка в разных написаниях (`www.`, без слеша) — нормализуется в один канонический URL, дубликат подписки не создаётся. → тест в Task 7.

---

## File Structure

```
theater-ticket-watcher/
├── watcher/
│   ├── __init__.py
│   ├── models.py             # Status, Session, ShowSnapshot, Event, ParseError
│   ├── state.py              # load/save state.json
│   ├── texts.py              # русские даты, тексты уведомлений
│   ├── parser_vakhtangov.py  # HTML → ShowSnapshot
│   ├── engine.py             # diff старого и нового состояния → события
│   ├── telegram.py           # обёртка Bot API с ретраем
│   ├── commands.py           # обработка сообщений/кнопок → Reply
│   ├── fetch.py              # httpx-загрузка страницы + парсинг
│   └── main.py               # оркестрация одного запуска
├── scripts/capture_fixture.py
├── tests/
│   ├── fixtures/             # synthetic_*.html + live.html
│   ├── test_models.py  test_state.py  test_texts.py  test_parser.py
│   ├── test_engine.py  test_telegram.py  test_commands.py  test_main.py
├── state.json
├── requirements.txt
├── pyproject.toml
├── README.md
└── .github/workflows/{watch.yml, ci.yml}
```

Каждый модуль — одна ответственность; `parser_vakhtangov.py` ничего не знает про Telegram и состояние, `engine.py` — чистая функция, `telegram.py` ничего не знает про билеты.

---

### Task 1: Каркас проекта и модели

**Files:**
- Create: `requirements.txt`, `pyproject.toml`, `watcher/__init__.py`, `watcher/models.py`
- Test: `tests/test_models.py`

**Interfaces:**
- Produces: `Status` (enum: `AVAILABLE="available"`, `SOLD_OUT="sold_out"`), `Session(stage, stage_title, dt, status, buy_url=None)` c `session.key == f"{stage}|{dt}"`, `ShowSnapshot(title, url, sessions: list[Session])`, `Event(kind, show_title, show_url, session)` где `kind ∈ {"tickets_appeared","new_date"}`, исключение `ParseError`.

- [ ] **Step 1: Создать окружение и конфиги**

```bash
cd /home/claude/theater-ticket-watcher
python3 -m venv .venv && source .venv/bin/activate
```

`requirements.txt`:
```
httpx>=0.27
beautifulsoup4>=4.12
pytest>=8
```

`pyproject.toml`:
```toml
[tool.pytest.ini_options]
testpaths = ["tests"]
```

```bash
pip install -r requirements.txt
mkdir -p watcher tests scripts tests/fixtures
touch watcher/__init__.py tests/__init__.py
echo ".venv/" > .gitignore
echo "__pycache__/" >> .gitignore
```

- [ ] **Step 2: Написать падающий тест**

`tests/test_models.py`:
```python
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
```

- [ ] **Step 3: Убедиться, что тест падает**

Run: `pytest tests/test_models.py -v`
Expected: FAIL — `ModuleNotFoundError` / `ImportError`.

- [ ] **Step 4: Реализовать**

`watcher/models.py`:
```python
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Literal


class Status(str, Enum):
    AVAILABLE = "available"
    SOLD_OUT = "sold_out"


@dataclass(frozen=True)
class Session:
    stage: str            # машинный id сцены: stageuid из buy-ссылки или слаг имени
    stage_title: str      # человеческое имя сцены, напр. "Основная сцена"
    dt: str               # время сеанса (МСК, наивное), ISO "2026-11-26T19:00"
    status: Status
    buy_url: str | None = None

    @property
    def key(self) -> str:
        return f"{self.stage}|{self.dt}"


@dataclass
class ShowSnapshot:
    title: str
    url: str
    sessions: list[Session]


@dataclass(frozen=True)
class Event:
    kind: Literal["tickets_appeared", "new_date"]
    show_title: str
    show_url: str
    session: Session


class ParseError(Exception):
    pass
```

- [ ] **Step 5: Прогнать тесты**

Run: `pytest tests/test_models.py -v`
Expected: 3 passed.

- [ ] **Step 6: Commit**

```bash
git add -A && git commit -m "feat: project scaffolding and domain models"
```

---

### Task 2: Состояние (`state.json`)

**Files:**
- Create: `watcher/state.py`, `state.json`
- Test: `tests/test_state.py`

**Interfaces:**
- Produces: `state.load(path: Path) -> dict`, `state.save(path: Path, state: dict) -> None`, константа `EMPTY = {"telegram_offset": 0, "subscriptions": {}}`. Схема словаря — как в спеке (`subscriptions[url] = {title, added_at, parse_error_notified, sessions}`; `sessions[key] = {status, buy_url, stage_title, dt}`).

- [ ] **Step 1: Написать падающий тест**

`tests/test_state.py`:
```python
import json

from watcher import state


def test_load_missing_file_returns_empty(tmp_path):
    st = state.load(tmp_path / "state.json")
    assert st == {"telegram_offset": 0, "subscriptions": {}}
    st["subscriptions"]["x"] = {}
    assert state.EMPTY["subscriptions"] == {}  # дефолт не мутировался


def test_roundtrip_utf8_stable(tmp_path):
    p = tmp_path / "state.json"
    st = {"telegram_offset": 5,
          "subscriptions": {"https://vakhtangov.ru/show/maskarade/": {
              "title": "Маскарад", "added_at": "2026-10-20T12:00:00+00:00",
              "parse_error_notified": False,
              "sessions": {"main|2026-11-26T19:00": {
                  "status": "sold_out", "buy_url": None,
                  "stage_title": "Основная сцена", "dt": "2026-11-26T19:00"}}}}}
    state.save(p, st)
    raw = p.read_text(encoding="utf-8")
    assert "Маскарад" in raw          # не \uXXXX
    assert raw.endswith("\n")
    assert state.load(p) == st
    assert json.loads(raw) == st
```

- [ ] **Step 2: Убедиться, что тест падает**

Run: `pytest tests/test_state.py -v` — Expected: FAIL (`ImportError`).

- [ ] **Step 3: Реализовать**

`watcher/state.py`:
```python
import copy
import json
from pathlib import Path

EMPTY = {"telegram_offset": 0, "subscriptions": {}}


def load(path: Path) -> dict:
    if not path.exists():
        return copy.deepcopy(EMPTY)
    return json.loads(path.read_text(encoding="utf-8"))


def save(path: Path, state: dict) -> None:
    path.write_text(
        json.dumps(state, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8")
```

Начальный `state.json` в корне репо:
```json
{
  "subscriptions": {},
  "telegram_offset": 0
}
```

- [ ] **Step 4: Прогнать тесты** — `pytest tests/test_state.py -v`, Expected: 2 passed.

- [ ] **Step 5: Commit** — `git add -A && git commit -m "feat: state load/save"`

---

### Task 3: Русские тексты и формат уведомлений

**Files:**
- Create: `watcher/texts.py`
- Test: `tests/test_texts.py`

**Interfaces:**
- Consumes: `Event`, `Session`, `Status` из Task 1.
- Produces: `human_dt(iso: str) -> str` («26 ноября, чт, 19:00»), `event_message(e: Event) -> tuple[str, list[tuple[str, str]]]` (текст HTML + url-кнопки `[("Купить билеты", buy_url)]`).

- [ ] **Step 1: Написать падающий тест**

`tests/test_texts.py`:
```python
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
```

- [ ] **Step 2: Убедиться, что падает** — `pytest tests/test_texts.py -v` → FAIL.

- [ ] **Step 3: Реализовать**

`watcher/texts.py`:
```python
from datetime import datetime
from html import escape

from .models import Event

MONTHS_GEN = ["января", "февраля", "марта", "апреля", "мая", "июня",
              "июля", "августа", "сентября", "октября", "ноября", "декабря"]
WEEKDAYS = ["пн", "вт", "ср", "чт", "пт", "сб", "вс"]


def human_dt(iso: str) -> str:
    d = datetime.fromisoformat(iso)
    return f"{d.day} {MONTHS_GEN[d.month - 1]}, {WEEKDAYS[d.weekday()]}, {d:%H:%M}"


def event_message(e: Event) -> tuple[str, list[tuple[str, str]]]:
    head = "появились билеты!" if e.kind == "tickets_appeared" else "новая дата в продаже!"
    stage = escape(e.session.stage_title) or "сцена не указана"
    text = (f"🎭 <b>{escape(e.show_title)}</b> — {head}\n"
            f"{human_dt(e.session.dt)} · {stage}\n"
            f'<a href="{escape(e.show_url)}">Страница спектакля</a>')
    buttons = [("Купить билеты", e.session.buy_url)] if e.session.buy_url else []
    return text, buttons
```

- [ ] **Step 4: Прогнать** — `pytest tests/test_texts.py -v` → 3 passed.
- [ ] **Step 5: Commit** — `git commit -am "feat: russian date formatting and notification texts"` (с `git add watcher/texts.py tests/test_texts.py`).

---

### Task 4: Парсер страницы vakhtangov.ru

**Files:**
- Create: `watcher/parser_vakhtangov.py`, `scripts/capture_fixture.py`, `tests/fixtures/synthetic_mixed.html`, `tests/fixtures/synthetic_soldout.html`, `tests/fixtures/no_schedule.html`, `tests/fixtures/live.html`
- Test: `tests/test_parser.py`

**Interfaces:**
- Consumes: `ParseError, Session, ShowSnapshot, Status` из Task 1.
- Produces: `parse_show_page(html: str, url: str, today: datetime.date) -> ShowSnapshot`.

Принцип парсера — не привязываться к CSS-классам: доступные сеансы берём из ссылок на `/tickets/buy/` (в их query уже есть машинные `stageuid` и `datetime`); распроданные — из текста «Билеты закончились», поднимаясь к родителю, в тексте которого есть дата вида «26 ноября … 19:00»; имя сцены — ближайший предшествующий заголовок со словом «сцена»/«зал»/«Арт-кафе»/«амфитеатр». Год для распроданных дат выводится: если месяц-день уже прошли в этом году — значит следующий год.

- [ ] **Step 1: Создать синтетические фикстуры**

`tests/fixtures/synthetic_mixed.html`:
```html
<html><body>
<h1>Маскарад</h1>
<h2>Основная сцена</h2>
<div class="row"><span>26 ноября, четверг, 19:00</span>
  <button disabled>Билеты закончились</button></div>
<div class="row"><span>26 декабря, суббота, 19:00</span>
  <a href="/tickets/buy/?stageuid=main&amp;datetime=2026-12-26-19-00-00">Купить билеты</a></div>
<h2>Новая сцена</h2>
<div class="row"><span>5 января, вторник, 18:00</span>
  <button disabled>Билеты закончились</button></div>
<div class="row"><span>9 января, суббота, 18:00</span>
  <a href="/tickets/buy/?datetime=broken">Купить билеты</a></div>
</body></html>
```

`tests/fixtures/synthetic_soldout.html`:
```html
<html><body>
<h1>Маскарад</h1>
<h2>Основная сцена</h2>
<div class="row"><span>26 ноября, четверг, 19:00</span>
  <button disabled>Билеты закончились</button></div>
</body></html>
```

`tests/fixtures/no_schedule.html`:
```html
<html><body><h1>Маскарад</h1><p>Описание спектакля без афиши.</p></body></html>
```

- [ ] **Step 2: Написать падающие тесты**

`tests/test_parser.py`:
```python
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
```

- [ ] **Step 3: Убедиться, что падают** — `pytest tests/test_parser.py -v` → FAIL (`ImportError`).

- [ ] **Step 4: Реализовать**

`watcher/parser_vakhtangov.py`:
```python
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
```

Замечание для исполнителя: `test_no_schedule_raises_parse_error` проходит за счёт «не найдено ни одного сеанса». Это осознанно строгое поведение из спека: страница без единого сеанса трактуется как parse error (бот предупредит один раз), а не как «дат нет» — на странице действующего спектакля афиша есть всегда.

- [ ] **Step 5: Прогнать** — `pytest tests/test_parser.py -v` → 4 passed, 1 skipped (live).

- [ ] **Step 6: Захватить живую фикстуру и прогнать инвариантный тест**

`scripts/capture_fixture.py`:
```python
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
```

Run:
```bash
python scripts/capture_fixture.py https://vakhtangov.ru/show/maskarade/ live.html
pytest tests/test_parser.py -v
```
Expected: 5 passed. **Если `test_live_fixture_invariants` упал** — открыть `tests/fixtures/live.html`, посмотреть реальную разметку блока афиши и поправить эвристики парсера (слова в `STAGE_WORDS`, глубину подъёма, `DATE_RE`) до зелёного состояния; синтетические тесты при этом должны остаться зелёными. Это единственное место плана, где код корректируется по живым данным.

- [ ] **Step 7: Дополнительно проверить руками**

```bash
python -c "
from datetime import date
from pathlib import Path
from watcher.parser_vakhtangov import parse_show_page
snap = parse_show_page(Path('tests/fixtures/live.html').read_text(encoding='utf-8'),
                       'https://vakhtangov.ru/show/maskarade/', date.today())
print(snap.title)
[print(s.key, s.status.value, s.buy_url) for s in snap.sessions]"
```
Expected: название «Маскарад» и сеансы, совпадающие с тем, что видно на сайте глазами.

- [ ] **Step 8: Commit** — `git add -A && git commit -m "feat: vakhtangov show page parser with fixtures"`

---

### Task 5: Engine — diff состояний → события

**Files:**
- Create: `watcher/engine.py`
- Test: `tests/test_engine.py`

**Interfaces:**
- Consumes: `Event, Session, ShowSnapshot, Status` из Task 1.
- Produces: `diff(stored: dict[str, dict], snapshot: ShowSnapshot, now: datetime) -> tuple[dict[str, dict], list[Event]]`. `stored` — словарь `sessions` подписки из state.json; возвращает новый такой словарь и события.

- [ ] **Step 1: Написать падающие тесты**

`tests/test_engine.py`:
```python
from datetime import datetime

from watcher.engine import diff
from watcher.models import Session, ShowSnapshot, Status

NOW = datetime(2026, 10, 20, 12, 0)
URL = "https://vakhtangov.ru/show/maskarade/"
BUY = "https://vakhtangov.ru/tickets/buy/?stageuid=main&datetime=2026-11-26-19-00-00"


def snap(*sessions):
    return ShowSnapshot("Маскарад", URL, list(sessions))


def stored_of(s: Session) -> dict:
    return {s.key: {"status": s.status.value, "buy_url": s.buy_url,
                    "stage_title": s.stage_title, "dt": s.dt}}


AV = Session("main", "Основная сцена", "2026-11-26T19:00", Status.AVAILABLE, BUY)
SO = Session("main", "Основная сцена", "2026-11-26T19:00", Status.SOLD_OUT)


def test_soldout_to_available_fires_tickets_appeared():
    new, events = diff(stored_of(SO), snap(AV), NOW)
    assert [e.kind for e in events] == ["tickets_appeared"]
    assert events[0].session.buy_url == BUY
    assert new[AV.key]["status"] == "available"


def test_new_available_session_fires_new_date():
    new, events = diff({}, snap(AV), NOW)
    assert [e.kind for e in events] == ["new_date"]


def test_new_soldout_session_is_silent():
    new, events = diff({}, snap(SO), NOW)
    assert events == [] and new[SO.key]["status"] == "sold_out"


def test_available_to_soldout_silent_and_rearms():
    new, events = diff(stored_of(AV), snap(SO), NOW)
    assert events == []
    # антиспам-цикл: после sold_out следующее появление снова уведомляет
    _, events2 = diff(new, snap(AV), NOW)
    assert [e.kind for e in events2] == ["tickets_appeared"]


def test_available_stays_available_no_repeat():
    new, events = diff(stored_of(AV), snap(AV), NOW)
    assert events == []


def test_past_session_dropped():
    past = Session("main", "Основная сцена", "2026-10-19T19:00", Status.AVAILABLE, BUY)
    new, events = diff(stored_of(past), snap(past), NOW)
    assert new == {} and events == []


def test_disappeared_session_dropped():
    new, events = diff(stored_of(SO), snap(), NOW)
    assert new == {} and events == []
```

- [ ] **Step 2: Убедиться, что падают** — `pytest tests/test_engine.py -v` → FAIL.

- [ ] **Step 3: Реализовать**

`watcher/engine.py`:
```python
from datetime import datetime

from .models import Event, ShowSnapshot, Status


def diff(stored: dict[str, dict], snapshot: ShowSnapshot,
         now: datetime) -> tuple[dict[str, dict], list[Event]]:
    """Сравнить сохранённые сеансы подписки со свежим снимком страницы.

    Возвращает (новый словарь sessions для state.json, события для уведомлений).
    Прошедшие и исчезнувшие со страницы сеансы выпадают из состояния.
    """
    events: list[Event] = []
    new_stored: dict[str, dict] = {}
    for s in snapshot.sessions:
        if datetime.fromisoformat(s.dt) < now:
            continue
        prev = stored.get(s.key)
        if prev is None:
            if s.status is Status.AVAILABLE:
                events.append(Event("new_date", snapshot.title, snapshot.url, s))
        elif prev["status"] == Status.SOLD_OUT.value and s.status is Status.AVAILABLE:
            events.append(Event("tickets_appeared", snapshot.title, snapshot.url, s))
        new_stored[s.key] = {"status": s.status.value, "buy_url": s.buy_url,
                             "stage_title": s.stage_title, "dt": s.dt}
    return new_stored, events
```

- [ ] **Step 4: Прогнать** — `pytest tests/test_engine.py -v` → 7 passed.
- [ ] **Step 5: Commit** — `git add -A && git commit -m "feat: state diff engine with anti-spam transitions"`

---

### Task 6: Обёртка Telegram Bot API

**Files:**
- Create: `watcher/telegram.py`
- Test: `tests/test_telegram.py`

**Interfaces:**
- Produces: класс `Telegram(token, transport=None)` c методами `get_updates(offset: int) -> list[dict]`, `send_message(chat_id, text, url_buttons=(), callback_buttons=())`, `answer_callback(callback_query_id)`; исключение `TelegramError`. Один повтор при любой ошибке, затем `TelegramError`. `transport` — httpx-транспорт для тестов.

- [ ] **Step 1: Написать падающие тесты**

`tests/test_telegram.py`:
```python
import json

import httpx
import pytest

from watcher.telegram import Telegram, TelegramError


def make_tg(handler):
    return Telegram("TOKEN", transport=httpx.MockTransport(handler))


def test_get_updates_parses_result():
    def handler(request):
        assert request.url.path == "/botTOKEN/getUpdates"
        body = json.loads(request.content)
        assert body["offset"] == 42
        return httpx.Response(200, json={"ok": True, "result": [{"update_id": 43}]})
    assert make_tg(handler).get_updates(42) == [{"update_id": 43}]


def test_send_message_builds_keyboard():
    seen = {}
    def handler(request):
        seen.update(json.loads(request.content))
        return httpx.Response(200, json={"ok": True, "result": {}})
    make_tg(handler).send_message(
        "1", "привет", url_buttons=[("Купить", "https://x")],
        callback_buttons=[("Удалить", "del|maskarade")])
    kb = seen["reply_markup"]["inline_keyboard"]
    assert kb == [[{"text": "Купить", "url": "https://x"}],
                  [{"text": "Удалить", "callback_data": "del|maskarade"}]]
    assert seen["parse_mode"] == "HTML" and seen["chat_id"] == "1"


def test_retry_once_then_success(monkeypatch):
    import watcher.telegram as tgmod
    monkeypatch.setattr(tgmod.time, "sleep", lambda s: None)
    calls = []
    def handler(request):
        calls.append(1)
        if len(calls) == 1:
            return httpx.Response(500)
        return httpx.Response(200, json={"ok": True, "result": []})
    assert make_tg(handler).get_updates(0) == []
    assert len(calls) == 2


def test_two_failures_raise(monkeypatch):
    import watcher.telegram as tgmod
    monkeypatch.setattr(tgmod.time, "sleep", lambda s: None)
    def handler(request):
        return httpx.Response(200, json={"ok": False, "description": "nope"})
    with pytest.raises(TelegramError):
        make_tg(handler).send_message("1", "x")
```

- [ ] **Step 2: Убедиться, что падают** — `pytest tests/test_telegram.py -v` → FAIL.

- [ ] **Step 3: Реализовать**

`watcher/telegram.py`:
```python
import time

import httpx


class TelegramError(Exception):
    pass


class Telegram:
    def __init__(self, token: str, transport: httpx.BaseTransport | None = None):
        self._client = httpx.Client(
            base_url=f"https://api.telegram.org/bot{token}",
            timeout=20, transport=transport)

    def _call(self, method: str, **params) -> object:
        for attempt in (1, 2):
            try:
                r = self._client.post(f"/{method}", json=params)
                data = r.json()
                if data.get("ok"):
                    return data["result"]
            except (httpx.HTTPError, ValueError):
                pass
            if attempt == 1:
                time.sleep(1)
        raise TelegramError(f"{method} failed after retry")

    def get_updates(self, offset: int) -> list[dict]:
        return self._call("getUpdates", offset=offset, timeout=0,
                          allowed_updates=["message", "callback_query"])

    def send_message(self, chat_id: str, text: str,
                     url_buttons=(), callback_buttons=()) -> None:
        params = {"chat_id": chat_id, "text": text, "parse_mode": "HTML",
                  "disable_web_page_preview": True}
        rows = ([[{"text": t, "url": u}] for t, u in url_buttons]
                + [[{"text": t, "callback_data": d}] for t, d in callback_buttons])
        if rows:
            params["reply_markup"] = {"inline_keyboard": rows}
        self._call("sendMessage", **params)

    def answer_callback(self, callback_query_id: str) -> None:
        self._call("answerCallbackQuery", callback_query_id=callback_query_id)
```

- [ ] **Step 4: Прогнать** — `pytest tests/test_telegram.py -v` → 4 passed.
- [ ] **Step 5: Commit** — `git add -A && git commit -m "feat: telegram bot api wrapper with retry"`

---

### Task 7: Команды бота

**Files:**
- Create: `watcher/commands.py`
- Test: `tests/test_commands.py`

**Interfaces:**
- Consumes: `ParseError, ShowSnapshot, Session, Status` (Task 1), `human_dt` (Task 3).
- Produces: `Reply(text, url_buttons=[], callback_buttons=[])` (dataclass) и `handle_update(update: dict, state: dict, my_chat_id: str, fetch_show: Callable[[str], ShowSnapshot]) -> list[Reply]`. Мутирует `state` (подписки, но НЕ `telegram_offset` — это делает main). `fetch_show` может бросать `ParseError` и сетевые исключения.

- [ ] **Step 1: Написать падающие тесты**

`tests/test_commands.py`:
```python
import pytest

from watcher.commands import Reply, handle_update
from watcher.models import ParseError, Session, ShowSnapshot, Status

CHAT = "111"
URL = "https://vakhtangov.ru/show/maskarade/"
SNAP = ShowSnapshot("Маскарад", URL, [
    Session("main", "Основная сцена", "2026-11-26T19:00", Status.SOLD_OUT),
    Session("main", "Основная сцена", "2026-12-26T19:00", Status.AVAILABLE,
            "https://vakhtangov.ru/tickets/buy/?stageuid=main&datetime=2026-12-26-19-00-00"),
])


def fresh_state():
    return {"telegram_offset": 0, "subscriptions": {}}


def msg(text, chat=CHAT):
    return {"update_id": 1, "message": {"chat": {"id": int(chat)}, "text": text}}


def test_subscribe_stores_baseline_and_confirms():
    st = fresh_state()
    replies = handle_update(msg(f"глянь {URL}"), st, CHAT, lambda u: SNAP)
    assert URL in st["subscriptions"]
    sub = st["subscriptions"][URL]
    assert sub["title"] == "Маскарад"
    assert sub["sessions"]["main|2026-12-26T19:00"]["status"] == "available"
    assert "Слежу" in replies[0].text and "26 декабря" in replies[0].text


def test_subscribe_normalizes_url_variants():
    st = fresh_state()
    handle_update(msg("https://www.vakhtangov.ru/show/maskarade"), st, CHAT, lambda u: SNAP)
    assert list(st["subscriptions"]) == [URL]  # Review Focus #5
    replies = handle_update(msg(URL), st, CHAT, lambda u: SNAP)
    assert "Уже слежу" in replies[0].text
    assert len(st["subscriptions"]) == 1


def test_foreign_chat_ignored():
    st = fresh_state()
    assert handle_update(msg(URL, chat="999"), st, CHAT, lambda u: SNAP) == []
    assert st["subscriptions"] == {}  # Review Focus #4


def test_subscribe_fetch_errors_reported():
    st = fresh_state()
    def boom_parse(u): raise ParseError("x")
    def boom_net(u): raise OSError("x")
    assert "не смогла" in handle_update(msg(URL), st, CHAT, boom_parse)[0].text
    assert "попробуй" in handle_update(msg(URL), st, CHAT, boom_net)[0].text
    assert st["subscriptions"] == {}


def test_list_and_delete():
    st = fresh_state()
    handle_update(msg(URL), st, CHAT, lambda u: SNAP)
    replies = handle_update(msg("/list"), st, CHAT, lambda u: SNAP)
    assert "Маскарад" in replies[0].text
    assert replies[0].callback_buttons == [("Удалить", "del|maskarade")]
    cb = {"update_id": 2, "callback_query": {
        "id": "cb1", "data": "del|maskarade",
        "message": {"chat": {"id": int(CHAT)}}}}
    replies = handle_update(cb, st, CHAT, lambda u: SNAP)
    assert "Больше не слежу" in replies[0].text
    assert st["subscriptions"] == {}


def test_unknown_text_gets_help():
    st = fresh_state()
    replies = handle_update(msg("привет"), st, CHAT, lambda u: SNAP)
    assert "vakhtangov.ru/show" in replies[0].text
```

- [ ] **Step 2: Убедиться, что падают** — `pytest tests/test_commands.py -v` → FAIL.

- [ ] **Step 3: Реализовать**

`watcher/commands.py`:
```python
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from html import escape

from .models import ParseError, Session
from .texts import human_dt

SHOW_URL_RE = re.compile(r"https?://(?:www\.)?vakhtangov\.ru/show/([\w-]+)/?")
HELP = ("Пришли мне ссылку на спектакль вида vakhtangov.ru/show/… — "
        "буду ловить билеты и новые даты.\n/list — мои подписки")


@dataclass
class Reply:
    text: str
    url_buttons: list = field(default_factory=list)
    callback_buttons: list = field(default_factory=list)


def _session_dict(s: Session) -> dict:
    return {"status": s.status.value, "buy_url": s.buy_url,
            "stage_title": s.stage_title, "dt": s.dt}


def _status_lines(sessions: dict) -> str:
    if not sessions:
        return "дат в афише нет"
    return "\n".join(
        f"• {human_dt(v['dt'])} — "
        f"{'есть билеты' if v['status'] == 'available' else 'билетов нет'}"
        for v in sorted(sessions.values(), key=lambda v: v["dt"]))


def handle_update(update: dict, state: dict, my_chat_id: str, fetch_show) -> list[Reply]:
    subs = state["subscriptions"]

    cq = update.get("callback_query")
    if cq:
        if str(cq["message"]["chat"]["id"]) != my_chat_id:
            return []
        slug = cq.get("data", "").removeprefix("del|")
        for url in list(subs):
            m = SHOW_URL_RE.search(url)
            if m and m.group(1) == slug:
                title = subs.pop(url)["title"]
                return [Reply(f"Больше не слежу за «{escape(title)}»")]
        return [Reply("Эта подписка уже удалена")]

    msg = update.get("message")
    if not msg or str(msg["chat"]["id"]) != my_chat_id:
        return []
    text = (msg.get("text") or "").strip()

    m = SHOW_URL_RE.search(text)
    if m:
        url = f"https://vakhtangov.ru/show/{m.group(1)}/"   # канонизация
        if url in subs:
            return [Reply(f"Уже слежу за «{escape(subs[url]['title'])}»")]
        try:
            snap = fetch_show(url)
        except ParseError:
            return [Reply("Открыла страницу, но не смогла её прочитать — проверь ссылку")]
        except Exception:
            return [Reply("Не получилось открыть страницу, попробуй ещё раз позже")]
        subs[url] = {
            "title": snap.title,
            "added_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "parse_error_notified": False,
            "sessions": {s.key: _session_dict(s) for s in snap.sessions},
        }
        return [Reply(f"✅ Слежу за «{escape(snap.title)}»\n"
                      + _status_lines(subs[url]["sessions"]))]

    if text == "/list":
        if not subs:
            return [Reply("Подписок пока нет.\n" + HELP)]
        replies = []
        for url, sub in subs.items():
            slug = SHOW_URL_RE.search(url).group(1)
            replies.append(Reply(
                f"<b>{escape(sub['title'])}</b>\n{_status_lines(sub['sessions'])}",
                callback_buttons=[("Удалить", f"del|{slug}")]))
        return replies

    return [Reply(HELP)]
```

Важно: при подписке текущие сеансы сохраняются как базовая линия — бот НЕ шлёт уведомления о билетах, которые были доступны уже в момент подписки (их статус виден в подтверждении).

- [ ] **Step 4: Прогнать** — `pytest tests/test_commands.py -v` → 6 passed.
- [ ] **Step 5: Commit** — `git add -A && git commit -m "feat: bot commands: subscribe, list, delete"`

---

### Task 8: fetch + оркестрация main

**Files:**
- Create: `watcher/fetch.py`, `watcher/main.py`
- Test: `tests/test_main.py`

**Interfaces:**
- Consumes: всё из Task 1–7.
- Produces: `fetch.fetch_show(url: str, client: httpx.Client | None = None) -> ShowSnapshot`, `fetch.UA` (строка User-Agent); `main.run(tg, chat_id: str, state: dict, fetch=fetch_show, now: datetime | None = None) -> dict` и `main.main()` (CLI-вход: env, load state → run → save state). `STATE_PATH` — `state.json` в корне репо.

- [ ] **Step 1: Написать падающие тесты**

`tests/test_main.py`:
```python
from datetime import datetime

import httpx
import pytest

from watcher.main import run
from watcher.models import ParseError, Session, ShowSnapshot, Status
from watcher.telegram import TelegramError

CHAT = "111"
URL = "https://vakhtangov.ru/show/maskarade/"
BUY = "https://vakhtangov.ru/tickets/buy/?stageuid=main&datetime=2026-11-26-19-00-00"
NOW = datetime(2026, 10, 20, 12, 0)


class FakeTg:
    def __init__(self, updates=()):
        self.updates = list(updates)
        self.sent = []
        self.fail_texts = set()   # тексты, на которых send_message бросает

    def get_updates(self, offset):
        return [u for u in self.updates if u["update_id"] >= offset]

    def send_message(self, chat_id, text, url_buttons=(), callback_buttons=()):
        if any(t in text for t in self.fail_texts):
            raise TelegramError("boom")
        self.sent.append((text, list(url_buttons)))

    def answer_callback(self, cb_id):
        pass


def sub_state(status="sold_out"):
    return {"telegram_offset": 0, "subscriptions": {URL: {
        "title": "Маскарад", "added_at": "2026-10-01T00:00:00+00:00",
        "parse_error_notified": False,
        "sessions": {"main|2026-11-26T19:00": {
            "status": status, "buy_url": BUY if status == "available" else None,
            "stage_title": "Основная сцена", "dt": "2026-11-26T19:00"}}}}}


def available_snap(u):
    return ShowSnapshot("Маскарад", URL, [
        Session("main", "Основная сцена", "2026-11-26T19:00", Status.AVAILABLE, BUY)])


def test_full_cycle_notifies_and_updates_state():
    tg = FakeTg()
    st = run(tg, CHAT, sub_state("sold_out"), fetch=available_snap, now=NOW)
    assert len(tg.sent) == 1
    text, buttons = tg.sent[0]
    assert "появились билеты" in text and buttons == [("Купить билеты", BUY)]
    assert st["subscriptions"][URL]["sessions"]["main|2026-11-26T19:00"]["status"] == "available"


def test_offset_advances_and_command_processed():
    upd = {"update_id": 7, "message": {"chat": {"id": int(CHAT)}, "text": "/list"}}
    tg = FakeTg(updates=[upd])
    st = run(tg, CHAT, sub_state("sold_out"), fetch=lambda u: sold_snap(), now=NOW)
    assert st["telegram_offset"] == 8
    assert any("Маскарад" in t for t, _ in tg.sent)


def sold_snap():
    return ShowSnapshot("Маскарад", URL, [
        Session("main", "Основная сцена", "2026-11-26T19:00", Status.SOLD_OUT)])


def test_network_error_skips_silently():
    def boom(u): raise httpx.ConnectError("down")
    tg = FakeTg()
    st = run(tg, CHAT, sub_state("sold_out"), fetch=boom, now=NOW)
    assert tg.sent == []
    assert st["subscriptions"][URL]["sessions"]["main|2026-11-26T19:00"]["status"] == "sold_out"


def test_parse_error_notifies_once():
    def boom(u): raise ParseError("x")
    tg = FakeTg()
    st = run(tg, CHAT, sub_state("sold_out"), fetch=boom, now=NOW)
    st = run(tg, CHAT, st, fetch=boom, now=NOW)
    warn = [t for t, _ in tg.sent if "Не могу прочитать" in t]
    assert len(warn) == 1
    # успешный парсинг сбрасывает флаг
    st = run(tg, CHAT, st, fetch=lambda u: sold_snap(), now=NOW)
    assert st["subscriptions"][URL]["parse_error_notified"] is False


def test_send_failure_keeps_old_status_for_retry():
    tg = FakeTg()
    tg.fail_texts = {"появились билеты"}
    st = run(tg, CHAT, sub_state("sold_out"), fetch=available_snap, now=NOW)
    # статус не зафиксирован — в следующем цикле уведомление повторится (Review Focus #3)
    assert st["subscriptions"][URL]["sessions"]["main|2026-11-26T19:00"]["status"] == "sold_out"
    tg.fail_texts = set()
    st = run(tg, CHAT, st, fetch=available_snap, now=NOW)
    assert any("появились билеты" in t for t, _ in tg.sent)
```

- [ ] **Step 2: Убедиться, что падают** — `pytest tests/test_main.py -v` → FAIL.

- [ ] **Step 3: Реализовать**

`watcher/fetch.py`:
```python
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
```

`watcher/main.py`:
```python
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

from . import state as state_mod
from .commands import handle_update
from .engine import diff
from .fetch import fetch_show
from .models import ParseError
from .telegram import Telegram, TelegramError
from .texts import event_message

MSK = timezone(timedelta(hours=3))
STATE_PATH = Path(__file__).resolve().parent.parent / "state.json"


def run(tg, chat_id: str, state: dict, fetch=fetch_show, now=None) -> dict:
    now = now or datetime.now(MSK).replace(tzinfo=None)

    # 1. команды из Telegram
    for upd in tg.get_updates(state["telegram_offset"]):
        state["telegram_offset"] = upd["update_id"] + 1
        for reply in handle_update(upd, state, chat_id, fetch):
            try:
                tg.send_message(chat_id, reply.text,
                                reply.url_buttons, reply.callback_buttons)
            except TelegramError:
                pass
        if upd.get("callback_query"):
            try:
                tg.answer_callback(upd["callback_query"]["id"])
            except TelegramError:
                pass

    # 2. проверка подписок
    for url, sub in list(state["subscriptions"].items()):
        try:
            snap = fetch(url)
        except ParseError:
            if not sub["parse_error_notified"]:
                try:
                    tg.send_message(chat_id, "⚠️ Не могу прочитать страницу "
                                    f"«{sub['title']}» — возможно, сайт изменился")
                    sub["parse_error_notified"] = True
                except TelegramError:
                    pass
            continue
        except Exception:          # сеть/5xx — тихо пропускаем цикл
            continue

        sub["parse_error_notified"] = False
        new_sessions, events = diff(sub["sessions"], snap, now)
        for e in events:
            text, buttons = event_message(e)
            try:
                tg.send_message(chat_id, text, url_buttons=buttons)
            except TelegramError:
                # не фиксируем статус — уведомление повторится в следующем цикле
                key = e.session.key
                if key in sub["sessions"]:
                    new_sessions[key] = sub["sessions"][key]
                else:
                    new_sessions.pop(key, None)
        sub["sessions"] = new_sessions
        sub["title"] = snap.title
    return state


def main() -> None:
    token = os.environ["TELEGRAM_BOT_TOKEN"]
    chat_id = os.environ["TELEGRAM_CHAT_ID"]
    st = state_mod.load(STATE_PATH)
    st = run(Telegram(token), chat_id, st)
    state_mod.save(STATE_PATH, st)


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Прогнать весь набор** — `pytest -v` → все тесты зелёные.
- [ ] **Step 5: Commit** — `git add -A && git commit -m "feat: fetch and main orchestration"`

---

### Task 9: GitHub Actions, README и финальная проверка

**Files:**
- Create: `.github/workflows/watch.yml`, `.github/workflows/ci.yml`, `README.md`

**Interfaces:**
- Consumes: `python -m watcher.main` (Task 8), `state.json` (Task 2), секреты `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`.

- [ ] **Step 1: Workflow мониторинга**

`.github/workflows/watch.yml`:
```yaml
name: watch
on:
  schedule:
    - cron: "*/5 * * * *"
  workflow_dispatch:
concurrency:
  group: watch
  cancel-in-progress: false
permissions:
  contents: write
jobs:
  watch:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"
          cache: pip
      - run: pip install -r requirements.txt
      - run: python -m watcher.main
        env:
          TELEGRAM_BOT_TOKEN: ${{ secrets.TELEGRAM_BOT_TOKEN }}
          TELEGRAM_CHAT_ID: ${{ secrets.TELEGRAM_CHAT_ID }}
      - name: Commit state
        run: |
          git config user.name "ticket-watcher"
          git config user.email "actions@users.noreply.github.com"
          git add state.json
          git diff --cached --quiet && exit 0
          git commit -m "chore: update state"
          git pull --rebase origin main
          git push
```

- [ ] **Step 2: Workflow тестов**

`.github/workflows/ci.yml`:
```yaml
name: ci
on:
  push:
    paths-ignore: ["state.json"]
jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"
          cache: pip
      - run: pip install -r requirements.txt
      - run: pytest -v
```

- [ ] **Step 3: README с инструкцией запуска**

`README.md`:
```markdown
# Ловец билетов (Вахтанговский театр)

Личный Telegram-бот: следит за страницами спектаклей vakhtangov.ru и
присылает уведомление со ссылкой на покупку, когда появились билеты
или открылась новая дата. Работает на GitHub Actions, раз в ~5 минут.

## Запуск с нуля

1. **Бот.** В Telegram открыть @BotFather → `/newbot` → получить токен.
2. **chat_id.** Написать своему боту любое сообщение, затем открыть
   `https://api.telegram.org/bot<ТОКЕН>/getUpdates` и взять
   `message.chat.id` из ответа.
3. **Репозиторий.** Создать **приватный** репозиторий на GitHub,
   запушить этот код в ветку `main`.
4. **Секреты.** Settings → Secrets and variables → Actions →
   добавить `TELEGRAM_BOT_TOKEN` и `TELEGRAM_CHAT_ID`.
5. **Проверка.** Вкладка Actions → workflow `watch` → Run workflow.
   Затем отправить боту ссылку вида `https://vakhtangov.ru/show/maskarade/` —
   в течение ~5 минут придёт подтверждение подписки.

## Команды бота

- ссылка на `vakhtangov.ru/show/…` — подписаться;
- `/list` — подписки и статусы дат, с кнопкой «Удалить».

## Как это работает

Каждые 5 минут workflow: забирает новые сообщения (`getUpdates`) →
скачивает страницы подписок → сравнивает со `state.json` → шлёт
уведомления о переходах «закончились → в продаже» и о новых датах →
коммитит обновлённый `state.json`.

## Нюансы

- GitHub cron не точен: реальный интервал 5–12 минут.
- GitHub отключает scheduled-workflow после 60 дней без активности в
  репозитории; коммиты `state.json` считаются активностью, но если
  бот долго «молчит» (нет изменений), просто перезапустить workflow
  или сделать любой коммит.
- Ответ бота на команды приходит с задержкой до одного цикла.
```

- [ ] **Step 4: Финальная проверка всего репозитория**

```bash
pytest -v                      # все зелёные
python -c "import yaml,sys; yaml.safe_load(open('.github/workflows/watch.yml')); yaml.safe_load(open('.github/workflows/ci.yml')); print('yaml ok')" \
  || pip install pyyaml && python -c "import yaml; yaml.safe_load(open('.github/workflows/watch.yml')); yaml.safe_load(open('.github/workflows/ci.yml')); print('yaml ok')"
git status --short             # ничего незакоммиченного, .venv игнорируется
```
Expected: тесты passed, `yaml ok`, чистый статус после коммита.

- [ ] **Step 5: Commit** — `git add -A && git commit -m "feat: github actions workflows and README"`

- [ ] **Step 6: Ручные шаги Кати (вне кода)**

Передать Кате чеклист из README: создать бота у @BotFather, узнать chat_id, создать приватный репозиторий, запушить, добавить два секрета, запустить workflow вручную и прислать боту первую ссылку. Дымовой тест: после подписки нажать `/list` и убедиться, что статусы совпадают с сайтом.

---

## Self-Review (выполнен)

1. **Spec coverage:** все разделы спека покрыты: модель состояния → Task 2, парсер и parse error → Task 4, пять переходов engine → Task 5, ретрай Telegram → Task 6, команды и базовая линия при подписке → Task 7, оркестрация/ошибки сети/однократное предупреждение/повтор уведомления при сбое отправки → Task 8, workflow + concurrency + секреты + README → Task 9. Пробелов не найдено.
2. **Placeholder scan:** TBD/«добавить обработку ошибок»/«аналогично задаче N» отсутствуют; весь код приведён целиком.
3. **Type consistency:** `Session.key`/`_session_dict`/схема `sessions` в state совпадают между Task 1/2/5/7/8; сигнатуры `handle_update`, `diff`, `event_message`, `fetch_show` используются ровно в том виде, в каком объявлены.
4. **Review Focus:** все 5 пунктов имеют именованные тесты в задачах-владельцах (см. пометки «Review Focus #N» в коде тестов).
