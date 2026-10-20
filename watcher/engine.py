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
