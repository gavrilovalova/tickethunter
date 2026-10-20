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
