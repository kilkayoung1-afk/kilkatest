"""Run user-submitted bots in isolated Docker containers."""

from __future__ import annotations

import asyncio
import logging
import shutil
from pathlib import Path

import docker
from docker.errors import APIError, NotFound
from docker.models.containers import Container

from .config import Config

logger = logging.getLogger(__name__)


class BotRunner:
    """Spawn / stop / inspect docker containers for user bots."""

    def __init__(self, config: Config):
        self._config = config
        self._client = docker.from_env()

    # --- helpers ---

    def _container_name(self, tg_id: int) -> str:
        return f"bothost_user_{tg_id}"

    def _user_dir(self, tg_id: int) -> Path:
        return self._config.user_bots_dir / str(tg_id)

    # --- public API ---

    async def save_script(self, tg_id: int, source: bytes) -> Path:
        """Persist the .py file to the per-user directory."""

        def _write() -> Path:
            user_dir = self._user_dir(tg_id)
            user_dir.mkdir(parents=True, exist_ok=True)
            target = user_dir / "bot.py"
            target.write_bytes(source)
            return target

        return await asyncio.to_thread(_write)

    async def start(self, tg_id: int) -> str:
        """Start the user's bot. Returns the new container id."""

        await self.stop(tg_id, remove=True)
        return await asyncio.to_thread(self._start_blocking, tg_id)

    async def stop(self, tg_id: int, *, remove: bool = True) -> bool:
        """Stop and (optionally) remove the user's container. Returns True if it existed."""

        return await asyncio.to_thread(self._stop_blocking, tg_id, remove)

    async def is_running(self, tg_id: int) -> bool:
        return await asyncio.to_thread(self._is_running_blocking, tg_id)

    async def logs(self, tg_id: int, tail: int = 50) -> str:
        return await asyncio.to_thread(self._logs_blocking, tg_id, tail)

    async def cleanup_files(self, tg_id: int) -> None:
        def _rm() -> None:
            user_dir = self._user_dir(tg_id)
            if user_dir.exists():
                shutil.rmtree(user_dir, ignore_errors=True)

        await asyncio.to_thread(_rm)

    # --- blocking helpers run via asyncio.to_thread ---

    def _start_blocking(self, tg_id: int) -> str:
        user_dir = self._user_dir(tg_id)
        user_dir.mkdir(parents=True, exist_ok=True)
        bot_file = user_dir / "bot.py"
        if not bot_file.exists():
            raise FileNotFoundError(f"User script not found: {bot_file}")

        pip_install = ""
        if self._config.user_bot_pip_packages:
            packages = " ".join(f'"{pkg}"' for pkg in self._config.user_bot_pip_packages)
            pip_install = (
                f"pip install --no-cache-dir --disable-pip-version-check --quiet {packages} && "
            )

        command = [
            "/bin/sh",
            "-c",
            f"{pip_install}exec python -u /app/bot.py",
        ]

        try:
            cpus = float(self._config.user_bot_cpus)
        except ValueError:
            cpus = 0.5
        nano_cpus = int(cpus * 1e9)

        try:
            container: Container = self._client.containers.run(
                image=self._config.user_bot_image,
                name=self._container_name(tg_id),
                command=command,
                volumes={
                    str(user_dir.resolve()): {"bind": "/app", "mode": "ro"},
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
                labels={"managed-by": "bothost", "user-tg-id": str(tg_id)},
            )
        except APIError:
            logger.exception("docker run failed for user %s", tg_id)
            raise

        logger.info("started bot for user %s as container %s", tg_id, container.id)
        return container.id or ""

    def _stop_blocking(self, tg_id: int, remove: bool) -> bool:
        name = self._container_name(tg_id)
        try:
            container = self._client.containers.get(name)
        except NotFound:
            return False
        try:
            container.stop(timeout=5)
        except APIError as exc:
            logger.warning("stopping container %s raised: %s", name, exc)
        if remove:
            try:
                container.remove(force=True)
            except APIError as exc:
                logger.warning("removing container %s raised: %s", name, exc)
        return True

    def _is_running_blocking(self, tg_id: int) -> bool:
        try:
            container = self._client.containers.get(self._container_name(tg_id))
        except NotFound:
            return False
        container.reload()
        return bool(container.status == "running")

    def _logs_blocking(self, tg_id: int, tail: int) -> str:
        try:
            container = self._client.containers.get(self._container_name(tg_id))
        except NotFound:
            return "Контейнер не найден — бот не запущен."
        raw = container.logs(tail=tail, stdout=True, stderr=True)
        if isinstance(raw, bytes):
            return raw.decode("utf-8", errors="replace")
        return str(raw)
