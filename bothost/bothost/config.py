"""Runtime configuration loaded from environment variables."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

from bothost.plans import DEFAULT_PLANS_JSON, Plan, parse_plans

load_dotenv()


def _parse_int_list(raw: str) -> list[int]:
    return [int(item.strip()) for item in raw.split(",") if item.strip()]


@dataclass(frozen=True)
class Config:
    bot_token: str
    admin_ids: list[int]
    plans: list[Plan]
    db_path: Path
    user_bots_dir: Path
    user_bots_dir_host: Path
    user_bot_image: str
    user_bot_memory: str
    user_bot_cpus: str
    log_level: str = "INFO"
    max_bots_per_user: int = 50
    bot_name_max_length: int = 32
    enabled_pip_install: bool = False
    pip_packages_extra: list[str] = field(default_factory=list)

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
        plans = parse_plans(os.environ.get("SUBSCRIPTION_PLANS", DEFAULT_PLANS_JSON))
        db_path = Path(os.environ.get("DB_PATH", "/data/bothost.sqlite3"))
        user_bots_dir = Path(os.environ.get("USER_BOTS_DIR", "/data/userbots"))
        user_bots_dir_host = Path(os.environ.get("USER_BOTS_DIR_HOST", str(user_bots_dir)))
        user_bot_image = os.environ.get("USER_BOT_IMAGE", "bothost-userbot:latest")
        user_bot_memory = os.environ.get("USER_BOT_MEMORY", "256m")
        user_bot_cpus = os.environ.get("USER_BOT_CPUS", "0.5")
        log_level = os.environ.get("LOG_LEVEL", "INFO").upper()
        max_bots = int(os.environ.get("MAX_BOTS_PER_USER", "50"))
        return cls(
            bot_token=bot_token,
            admin_ids=admin_ids,
            plans=plans,
            db_path=db_path,
            user_bots_dir=user_bots_dir,
            user_bots_dir_host=user_bots_dir_host,
            user_bot_image=user_bot_image,
            user_bot_memory=user_bot_memory,
            user_bot_cpus=user_bot_cpus,
            log_level=log_level,
            max_bots_per_user=max_bots,
        )

    def is_admin(self, tg_id: int) -> bool:
        return tg_id in self.admin_ids
