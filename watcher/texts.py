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
