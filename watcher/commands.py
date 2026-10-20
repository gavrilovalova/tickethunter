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
