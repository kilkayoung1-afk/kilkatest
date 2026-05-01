"""Handle ZIP-archive bot uploads: validate, extract, install pinned deps."""

from __future__ import annotations

import asyncio
import logging
import re
import shutil
import zipfile
from dataclasses import dataclass
from pathlib import Path

from bothost.validator import ValidationResult, validate_user_script

logger = logging.getLogger(__name__)

MAX_ARCHIVE_BYTES = 5 * 1024 * 1024  # 5 MiB compressed
MAX_EXTRACTED_BYTES = 20 * 1024 * 1024  # 20 MiB total uncompressed
MAX_FILES = 100
ALLOWED_SUFFIXES = {
    ".py",
    ".txt",
    ".json",
    ".yaml",
    ".yml",
    ".env",
    ".ini",
    ".cfg",
    ".toml",
    ".html",
    ".css",
    ".sql",
    ".csv",
    ".md",
}
MAX_REQ_LINES = 100
MAX_INSTALL_BYTES = 250 * 1024 * 1024  # 250 MiB site-packages cap


@dataclass(slots=True)
class BundleResult:
    ok: bool
    entry: str | None = None  # relative path to bot.py inside extracted dir
    requirements: list[str] | None = None
    error: str | None = None
    warnings: list[str] | None = None


def _is_safe_member(name: str) -> bool:
    if not name:
        return False
    norm = name.replace("\\", "/")
    if norm.startswith("/") or ".." in norm.split("/"):
        return False
    return True


def _has_allowed_extension(filename: str) -> bool:
    """Whitelist check that handles dotfiles (e.g. `.env`, `.gitignore`).

    `Path('.env').suffix` is `''` because Python treats leading-dot files as
    extension-less; fall back to the full base name in that case.
    """
    base = Path(filename).name
    suffix = Path(base).suffix.lower()
    if suffix in ALLOWED_SUFFIXES:
        return True
    if not suffix and base.startswith(".") and base.lower() in ALLOWED_SUFFIXES:
        return True
    return False


def _validate_requirement_line(line: str) -> str | None:
    line = line.strip()
    if not line or line.startswith("#"):
        return None
    if any(line.startswith(p) for p in ("git+", "hg+", "svn+", "bzr+", "file:")):
        raise ValueError(f"VCS/file requirements запрещены: {line!r}")
    if line.startswith("-"):
        raise ValueError(f"pip-флаги в requirements.txt запрещены: {line!r}")
    if not re.fullmatch(r"[A-Za-z0-9._\-\[\]]+(\s*[<>=!~]=?\s*[A-Za-z0-9._\-+*]+)?", line):
        raise ValueError(f"Неподдерживаемый формат строки: {line!r}")
    return line


def parse_requirements(text: str) -> list[str]:
    out: list[str] = []
    for raw in text.splitlines()[:MAX_REQ_LINES]:
        normalised = _validate_requirement_line(raw)
        if normalised is not None:
            out.append(normalised)
    if len(out) > 50:
        raise ValueError("Слишком много зависимостей (макс 50).")
    return out


def _scan_python_files(root: Path) -> list[ValidationResult]:
    results: list[ValidationResult] = []
    for file in root.rglob("*.py"):
        try:
            data = file.read_bytes()
        except OSError as exc:
            results.append(ValidationResult(ok=False, error=f"{file.name}: {exc}"))
            continue
        result = validate_user_script(data)
        if not result.ok:
            return [ValidationResult(ok=False, error=f"{file.relative_to(root)}: {result.error}")]
        results.append(result)
    return results


async def extract_zip(*, archive_bytes: bytes, target_dir: Path) -> BundleResult:
    """Validate and extract a ZIP archive into `target_dir`. Returns BundleResult.

    `target_dir` will contain the extracted files on success and bot.py at the
    top-level (or inside a single top-level folder).
    """

    def _do() -> BundleResult:
        if len(archive_bytes) > MAX_ARCHIVE_BYTES:
            return BundleResult(
                ok=False,
                error=f"ZIP больше {MAX_ARCHIVE_BYTES // 1024} КБ.",
            )

        target_dir.mkdir(parents=True, exist_ok=True)
        for child in target_dir.iterdir():
            if child.is_dir():
                shutil.rmtree(child, ignore_errors=True)
            else:
                child.unlink(missing_ok=True)

        # Use a BytesIO so we don't write the archive to disk first.
        import io

        try:
            zf = zipfile.ZipFile(io.BytesIO(archive_bytes))
        except zipfile.BadZipFile:
            return BundleResult(ok=False, error="Файл не похож на корректный ZIP.")

        with zf:
            members = zf.infolist()
            if len(members) > MAX_FILES:
                return BundleResult(ok=False, error=f"В архиве больше {MAX_FILES} файлов.")
            total = 0
            for m in members:
                if m.is_dir():
                    continue
                if not _is_safe_member(m.filename):
                    return BundleResult(
                        ok=False,
                        error=f"Подозрительный путь в архиве: {m.filename!r}.",
                    )
                if not _has_allowed_extension(m.filename):
                    return BundleResult(
                        ok=False,
                        error=(
                            f"Недопустимое расширение: {m.filename}. "
                            f"Разрешены: {', '.join(sorted(ALLOWED_SUFFIXES))}."
                        ),
                    )
                total += m.file_size
                if total > MAX_EXTRACTED_BYTES:
                    return BundleResult(
                        ok=False,
                        error=f"После распаковки больше {MAX_EXTRACTED_BYTES // 1024 // 1024} МБ.",
                    )
            zf.extractall(target_dir)

        # If the archive is wrapped in a single top-level folder, hoist its contents up.
        entries = [p for p in target_dir.iterdir() if not p.name.startswith(".")]
        if len(entries) == 1 and entries[0].is_dir():
            wrapper = entries[0]
            for child in wrapper.iterdir():
                shutil.move(str(child), str(target_dir / child.name))
            wrapper.rmdir()

        bot_file = target_dir / "bot.py"
        if not bot_file.exists():
            return BundleResult(ok=False, error="В архиве нет файла bot.py в корне.")

        scan_results = _scan_python_files(target_dir)
        for r in scan_results:
            if not r.ok:
                return BundleResult(ok=False, error=r.error)
        warnings: list[str] = []
        for r in scan_results:
            if r.warnings:
                warnings.extend(r.warnings)

        requirements: list[str] | None = None
        req_file = target_dir / "requirements.txt"
        if req_file.exists():
            try:
                requirements = parse_requirements(req_file.read_text("utf-8"))
            except ValueError as exc:
                return BundleResult(ok=False, error=str(exc))
            except UnicodeDecodeError:
                return BundleResult(ok=False, error="requirements.txt не в UTF-8.")

        return BundleResult(
            ok=True,
            entry="bot.py",
            requirements=requirements,
            warnings=warnings or None,
        )

    return await asyncio.to_thread(_do)


async def install_requirements(
    *,
    requirements: list[str],
    site_packages_dir: Path,
    image: str,
    docker_client: object,  # docker.DockerClient — kept loose to avoid heavy import
    timeout_sec: int = 180,
) -> tuple[bool, str]:
    """Run `pip install --target=<site_packages_dir>` inside an ephemeral container.

    The install container has its OWN network and only PyPI access (default
    bridge). It runs as a non-root user. After install, we check the resulting
    site-packages size against MAX_INSTALL_BYTES.
    """

    def _do() -> tuple[bool, str]:
        site_packages_dir.mkdir(parents=True, exist_ok=True)
        # Clean previous install — fresh state per upload.
        for entry in site_packages_dir.iterdir():
            if entry.is_dir():
                shutil.rmtree(entry, ignore_errors=True)
            else:
                entry.unlink(missing_ok=True)

        from typing import Any, cast

        client = cast(Any, docker_client)
        try:
            container = client.containers.run(
                image=image,
                command=[
                    "pip",
                    "install",
                    "--no-cache-dir",
                    "--no-compile",
                    "--target",
                    "/install",
                    *requirements,
                ],
                volumes={
                    str(site_packages_dir): {"bind": "/install", "mode": "rw"},
                },
                detach=True,
                mem_limit="512m",
                nano_cpus=int(1.0 * 1e9),
                cap_drop=["ALL"],
                security_opt=["no-new-privileges:true"],
                pids_limit=128,
                network_mode="bridge",
                labels={"managed-by": "bothost", "purpose": "deps-install"},
                user="0:0",  # pip needs to write packages; container is throwaway
            )
        except Exception as exc:  # noqa: BLE001
            return False, f"Ошибка запуска pip-сандбокса: {exc}"

        try:
            result = container.wait(timeout=timeout_sec)
            logs = container.logs().decode(errors="replace")[-3000:]
            exit_code = int(result.get("StatusCode", 1))
        except Exception as exc:  # noqa: BLE001
            try:
                container.kill()
            except Exception:
                pass
            return False, f"pip превысил таймаут ({timeout_sec}s) или сломался: {exc}"
        finally:
            try:
                container.remove(force=True)
            except Exception:
                pass

        if exit_code != 0:
            return False, f"pip упал (exit={exit_code}):\n{logs}"

        total = sum(p.stat().st_size for p in site_packages_dir.rglob("*") if p.is_file())
        if total > MAX_INSTALL_BYTES:
            shutil.rmtree(site_packages_dir, ignore_errors=True)
            site_packages_dir.mkdir()
            return False, (
                f"Размер зависимостей {total // 1024 // 1024} МБ "
                f"больше лимита {MAX_INSTALL_BYTES // 1024 // 1024} МБ."
            )

        return True, logs[-500:] if logs else "ok"

    return await asyncio.to_thread(_do)
