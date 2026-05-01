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
            self._wipe_app_files(user_dir)
            user_dir.mkdir(parents=True, exist_ok=True)
            (user_dir / "data").mkdir(exist_ok=True)
            target = user_dir / "bot.py"
            target.write_bytes(source)
            return target

        return await asyncio.to_thread(_write)

    def user_dir(self, tg_id: int, bot_id: int) -> Path:
        """Public accessor used by the bundle handler to extract a ZIP into."""
        return self._user_dir(tg_id, bot_id)

    def site_packages_dir(self, tg_id: int, bot_id: int) -> Path:
        return self._user_dir(tg_id, bot_id) / "data" / "site-packages"

    def docker_client(self) -> object:
        return self._client

    def _wipe_app_files(self, user_dir: Path) -> None:
        """Remove old bot files but keep /data so user state survives uploads."""
        if not user_dir.exists():
            return
        for entry in user_dir.iterdir():
            if entry.name == "data":
                continue
            if entry.is_dir():
                shutil.rmtree(entry, ignore_errors=True)
            else:
                entry.unlink(missing_ok=True)

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
        # User container runs as `nobody` (uid 65534) so the writable mount
        # must be world-writable. We don't chown to keep parent permissions intact.
        try:
            data_dir.chmod(0o777)
        except OSError:
            pass
        host_user_dir = self._user_dir_host(tg_id, bot_id)
        host_data_dir = host_user_dir / "data"

        try:
            cpus = float(self._config.user_bot_cpus)
        except ValueError:
            cpus = 0.5
        nano_cpus = int(cpus * 1e9)

        env = {
            "PYTHONUNBUFFERED": "1",
            "PYTHONDONTWRITEBYTECODE": "1",
            # Make user-installed deps importable; site-packages is inside /app/data.
            "PYTHONPATH": "/app/data/site-packages:/app",
            "HOME": "/app/data",
        }
        ulimits = [
            docker.types.Ulimit(name="nofile", soft=256, hard=512),
            docker.types.Ulimit(name="nproc", soft=64, hard=128),
            docker.types.Ulimit(name="fsize", soft=50_000_000, hard=50_000_000),
        ]

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
                user="65534:65534",
                environment=env,
                mem_limit=self._config.user_bot_memory,
                memswap_limit=self._config.user_bot_memory,
                nano_cpus=nano_cpus,
                cap_drop=["ALL"],
                security_opt=["no-new-privileges:true"],
                pids_limit=128,
                ulimits=ulimits,
                tmpfs={"/tmp": "size=64m,mode=1777"},
                read_only=True,
                network_mode=self._config.user_bot_network,
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
