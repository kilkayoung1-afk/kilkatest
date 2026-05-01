"""Run user-submitted bots in isolated Docker containers."""

from __future__ import annotations

import asyncio
import logging
import re
import shutil
from pathlib import Path

import docker
from docker.errors import APIError, NotFound

from bothost.config import Config

logger = logging.getLogger(__name__)


_NAME_PATTERN = re.compile(r"^[a-zA-Z0-9_-]{1,32}$")


def slug_name(name: str) -> str | None:
    """Return the bot name if it matches the allowed pattern, else None."""
    if not name:
        return None
    cleaned = name.strip()
    if not _NAME_PATTERN.match(cleaned):
        return None
    return cleaned


def make_container_name(tg_id: int, bot_id: int) -> str:
    return f"bothost_user_{tg_id}_{bot_id}"


class BotRunner:
    """Spawn / stop / inspect docker containers for user bots."""

    def __init__(self, config: Config):
        self._config = config
        self._client = docker.from_env()

    def _user_dir(self, tg_id: int, bot_id: int) -> Path:
        return self._config.user_bots_dir / str(tg_id) / str(bot_id)

    def _user_dir_host(self, tg_id: int, bot_id: int) -> Path:
        """Path as visible to the host docker daemon (which spawns child containers)."""
        return self._config.user_bots_dir_host / str(tg_id) / str(bot_id)

    # --- public API ---

    async def save_script(self, *, tg_id: int, bot_id: int, source: bytes) -> Path:
        def _write() -> Path:
            user_dir = self._user_dir(tg_id, bot_id)
            user_dir.mkdir(parents=True, exist_ok=True)
            (user_dir / "data").mkdir(exist_ok=True)
            target = user_dir / "bot.py"
            target.write_bytes(source)
            return target

        return await asyncio.to_thread(_write)

    async def start(self, *, tg_id: int, bot_id: int, container_name: str) -> str:
        await self._stop_blocking_async(container_name, remove=True)
        return await asyncio.to_thread(
            self._start_blocking, tg_id=tg_id, bot_id=bot_id, container_name=container_name
        )

    async def stop(self, container_name: str, *, remove: bool = True) -> bool:
        return await asyncio.to_thread(self._stop_blocking, container_name, remove)

    async def is_running(self, container_name: str) -> bool:
        return await asyncio.to_thread(self._is_running_blocking, container_name)

    async def logs(self, container_name: str, tail: int = 50) -> str:
        return await asyncio.to_thread(self._logs_blocking, container_name, tail)

    async def cleanup_files(self, *, tg_id: int, bot_id: int) -> None:
        def _rm() -> None:
            user_dir = self._user_dir(tg_id, bot_id)
            if user_dir.exists():
                shutil.rmtree(user_dir, ignore_errors=True)

        await asyncio.to_thread(_rm)

    async def _stop_blocking_async(self, container_name: str, *, remove: bool) -> bool:
        return await asyncio.to_thread(self._stop_blocking, container_name, remove)

    # --- blocking helpers ---

    def _start_blocking(self, *, tg_id: int, bot_id: int, container_name: str) -> str:
        user_dir = self._user_dir(tg_id, bot_id)
        bot_file = user_dir / "bot.py"
        if not bot_file.exists():
            raise FileNotFoundError(f"User script not found: {bot_file}")
        data_dir = user_dir / "data"
        data_dir.mkdir(exist_ok=True)
        host_user_dir = self._user_dir_host(tg_id, bot_id)
        host_data_dir = host_user_dir / "data"

        try:
            cpus = float(self._config.user_bot_cpus)
        except ValueError:
            cpus = 0.5
        nano_cpus = int(cpus * 1e9)

        try:
            container = self._client.containers.run(
                image=self._config.user_bot_image,
                name=container_name,
                volumes={
                    str(host_user_dir): {"bind": "/app", "mode": "ro"},
                    str(host_data_dir): {"bind": "/app/data", "mode": "rw"},
                },
                working_dir="/app",
                detach=True,
                mem_limit=self._config.user_bot_memory,
                nano_cpus=nano_cpus,
                cap_drop=["ALL"],
                security_opt=["no-new-privileges:true"],
                pids_limit=128,
                tmpfs={"/tmp": "size=64m,mode=1777"},
                read_only=True,
                network_mode="bridge",
                restart_policy={"Name": "no"},
                labels={
                    "managed-by": "bothost",
                    "user-tg-id": str(tg_id),
                    "bot-id": str(bot_id),
                },
            )
        except APIError:
            logger.exception("docker run failed for user %s bot %s", tg_id, bot_id)
            raise

        logger.info("started bot %s for user %s as container %s", bot_id, tg_id, container.id)
        return container.id or ""

    def _stop_blocking(self, container_name: str, remove: bool) -> bool:
        try:
            container = self._client.containers.get(container_name)
        except NotFound:
            return False
        try:
            container.stop(timeout=5)
        except APIError as exc:
            logger.warning("stopping container %s raised: %s", container_name, exc)
        if remove:
            try:
                container.remove(force=True)
            except APIError as exc:
                logger.warning("removing container %s raised: %s", container_name, exc)
        return True

    def _is_running_blocking(self, container_name: str) -> bool:
        try:
            container = self._client.containers.get(container_name)
        except NotFound:
            return False
        container.reload()
        return bool(container.status == "running")

    def _logs_blocking(self, container_name: str, tail: int) -> str:
        try:
            container = self._client.containers.get(container_name)
        except NotFound:
            return "Контейнер не найден — бот не запущен."
        raw = container.logs(tail=tail, stdout=True, stderr=True)
        if isinstance(raw, bytes):
            return raw.decode("utf-8", errors="replace")
        return str(raw)
