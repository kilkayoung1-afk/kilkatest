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
    user_bot_network: str = "bridge"
    log_level: str = "INFO"
    max_bots_per_user: int = 50
    bot_name_max_length: int = 32
    enabled_pip_install: bool = False
    pip_packages_extra: list[str] = field(default_factory=list)
    admin_contact_url: str = ""
    admin_contact_label: str = "Написать админу"

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
        user_bot_network = os.environ.get("USER_BOT_NETWORK", "bridge")
        log_level = os.environ.get("LOG_LEVEL", "INFO").upper()
        max_bots = int(os.environ.get("MAX_BOTS_PER_USER", "50"))
        admin_contact_url = _normalize_contact_url(os.environ.get("ADMIN_CONTACT_URL", "").strip())
        admin_contact_label = os.environ.get("ADMIN_CONTACT_LABEL", "Написать админу").strip()
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
            user_bot_network=user_bot_network,
            log_level=log_level,
            max_bots_per_user=max_bots,
            admin_contact_url=admin_contact_url,
            admin_contact_label=admin_contact_label or "Написать админу",
        )

    def is_admin(self, tg_id: int) -> bool:
        return tg_id in self.admin_ids

    def admin_contact_html(self) -> str:
        """Return an `<a href>` link to the admin, or a fallback for empty config."""
        if self.admin_contact_url:
            return f'<a href="{self.admin_contact_url}">{self.admin_contact_label}</a>'
        if self.admin_ids:
            return f'<a href="tg://user?id={self.admin_ids[0]}">{self.admin_contact_label}</a>'
        return self.admin_contact_label


def _normalize_contact_url(value: str) -> str:
    """Accept @username, t.me/username, or a full https://t.me/username URL."""
    if not value:
        return ""
    if value.startswith(("http://", "https://", "tg://")):
        return value
    if value.startswith("@"):
        return f"https://t.me/{value[1:]}"
    if value.startswith("t.me/") or value.startswith("telegram.me/"):
        return f"https://{value}"
    return f"https://t.me/{value}"
