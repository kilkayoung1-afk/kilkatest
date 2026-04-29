"""Конфигурация приложения. Загружается из .env."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

ROOT_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT_DIR / "data"
DATA_DIR.mkdir(exist_ok=True)


def _parse_ids(raw: str | None) -> list[int]:
    if not raw:
        return []
    out: list[int] = []
    for part in raw.replace(";", ",").split(","):
        part = part.strip()
        if not part:
            continue
        try:
            out.append(int(part))
        except ValueError:
            continue
    return out


@dataclass(slots=True)
class Settings:
    bot_token: str
    admin_ids: list[int] = field(default_factory=list)
    database_url: str = "sqlite+aiosqlite:///data/constructor.db"
    log_level: str = "INFO"
    max_bots_per_user: int = 0

    @classmethod
    def load(cls) -> Settings:
        token = os.getenv("BOT_TOKEN", "").strip()
        if not token:
            raise RuntimeError(
                "BOT_TOKEN не задан. Создайте .env (см. .env.example) и укажите токен главного бота."
            )
        return cls(
            bot_token=token,
            admin_ids=_parse_ids(os.getenv("ADMIN_IDS")),
            database_url=os.getenv("DATABASE_URL", "sqlite+aiosqlite:///data/constructor.db"),
            log_level=os.getenv("LOG_LEVEL", "INFO").upper(),
            max_bots_per_user=int(os.getenv("MAX_BOTS_PER_USER", "0") or 0),
        )
