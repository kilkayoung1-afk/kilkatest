"""Runtime configuration loaded from environment variables."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()


def _parse_int_list(raw: str) -> list[int]:
    return [int(item.strip()) for item in raw.split(",") if item.strip()]


def _parse_str_list(raw: str) -> list[str]:
    return [item.strip() for item in raw.split(",") if item.strip()]


@dataclass(frozen=True)
class Config:
    bot_token: str
    admin_ids: list[int]
    subscription_stars: int
    subscription_days: int
    db_path: Path
    user_bots_dir: Path
    user_bot_image: str
    user_bot_memory: str
    user_bot_cpus: str
    user_bot_pip_packages: list[str] = field(default_factory=list)
    log_level: str = "INFO"

    @classmethod
    def from_env(cls) -> Config:
        bot_token = os.environ.get("BOT_TOKEN", "").strip()
        if not bot_token:
            raise RuntimeError(
                "BOT_TOKEN is not set. Create a bot via @BotFather and put the token in .env."
            )
        admin_ids = _parse_int_list(os.environ.get("ADMIN_IDS", ""))
        if not admin_ids:
            raise RuntimeError("ADMIN_IDS is empty — set at least one Telegram user id in .env.")
        subscription_stars = int(os.environ.get("SUBSCRIPTION_STARS", "50"))
        subscription_days = int(os.environ.get("SUBSCRIPTION_DAYS", "7"))
        db_path = Path(os.environ.get("DB_PATH", "/data/bothost.sqlite3"))
        user_bots_dir = Path(os.environ.get("USER_BOTS_DIR", "/data/userbots"))
        user_bot_image = os.environ.get("USER_BOT_IMAGE", "python:3.12-slim")
        user_bot_memory = os.environ.get("USER_BOT_MEMORY", "256m")
        user_bot_cpus = os.environ.get("USER_BOT_CPUS", "0.5")
        pip_packages = _parse_str_list(os.environ.get("USER_BOT_PIP_PACKAGES", ""))
        log_level = os.environ.get("LOG_LEVEL", "INFO").upper()
        return cls(
            bot_token=bot_token,
            admin_ids=admin_ids,
            subscription_stars=subscription_stars,
            subscription_days=subscription_days,
            db_path=db_path,
            user_bots_dir=user_bots_dir,
            user_bot_image=user_bot_image,
            user_bot_memory=user_bot_memory,
            user_bot_cpus=user_bot_cpus,
            user_bot_pip_packages=pip_packages,
            log_level=log_level,
        )

    def is_admin(self, tg_id: int) -> bool:
        return tg_id in self.admin_ids
