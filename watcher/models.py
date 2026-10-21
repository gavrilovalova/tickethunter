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


class AvailabilityError(ParseError):
    """data.json (источник правды о билетах) недоступен по смыслу:
    пустой или неожиданной структуры."""
