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
