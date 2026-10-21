import os
from datetime import datetime, timedelta, timezone
from html import escape
from pathlib import Path

from . import state as state_mod
from .commands import handle_update
from .engine import diff
from .fetch import fetch_availability, fetch_show
from .models import ParseError
from .telegram import Telegram, TelegramError
from .texts import event_message

MSK = timezone(timedelta(hours=3))
STATE_PATH = Path(__file__).resolve().parent.parent / "state.json"


def _default_fetch():
    """fetch(url) с одним data.json на весь запуск (он общий для всех страниц)."""
    cache: dict = {}

    def fetch(url: str):
        if "availability" not in cache:
            cache["availability"] = fetch_availability()
        return fetch_show(url, availability=cache["availability"])

    return fetch


def run(tg, chat_id: str, state: dict, fetch=None, now=None) -> dict:
    fetch = fetch or _default_fetch()
    now = now or datetime.now(MSK).replace(tzinfo=None)

    # 1. команды из Telegram
    for upd in tg.get_updates(state["telegram_offset"]):
        state["telegram_offset"] = upd["update_id"] + 1
        try:
            replies = handle_update(upd, state, chat_id, fetch)
        except Exception:
            # «ядовитый» апдейт не должен ронять запуск до сохранения state,
            # иначе бот вечно перечитывает один и тот же апдейт
            replies = []
        for reply in replies:
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
                                    f"«{escape(sub['title'])}» — возможно, сайт изменился")
                    sub["parse_error_notified"] = True
                except TelegramError:
                    pass
            continue
        except Exception:          # сеть/5xx — тихо пропускаем цикл
            continue

        try:
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
        except Exception:          # одна битая подписка не должна ронять весь запуск
            continue
    return state


def main() -> None:
    token = os.environ["TELEGRAM_BOT_TOKEN"]
    chat_id = os.environ["TELEGRAM_CHAT_ID"]
    st = state_mod.load(STATE_PATH)
    try:
        run(Telegram(token), chat_id, st)    # мутирует st на месте
    finally:
        state_mod.save(STATE_PATH, st)


if __name__ == "__main__":
    main()
