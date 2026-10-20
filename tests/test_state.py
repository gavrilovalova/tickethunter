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
