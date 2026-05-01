"""Sanity checks for user-submitted Python files before we run them."""

from __future__ import annotations

import ast
import re
from dataclasses import dataclass

MAX_FILE_BYTES = 1 * 1024 * 1024  # 1 MiB

# Soft-warning calls — common but worth flagging.
_SUSPICIOUS_CALLS: set[str] = {"eval", "exec", "compile"}

# Hard-block patterns (regex on raw source) — typical stealer/malware signatures.
_DENY_PATTERNS: list[tuple[str, str]] = [
    (r"\.ssh/(id_rsa|id_ed25519|authorized_keys|known_hosts)",
     "доступ к SSH-ключам хоста"),
    (r"\.aws/credentials|\.aws/config",
     "доступ к AWS credentials"),
    (r"/etc/(shadow|passwd|sudoers)",
     "чтение системных файлов"),
    (r"~/\.config/(google-chrome|chromium|Mozilla|BraveSoftware|Microsoft/Edge)",
     "сбор браузерных данных"),
    (r"Login Data|Cookies|Web Data|Local State",
     "сбор браузерных профилей"),
    (r"wallet\.dat|MetaMask|Exodus|Atomic|Electrum|keystore",
     "сбор крипто-кошельков"),
    # Note: "subprocess + shell-util" is split across two patterns to keep the regex simple.
    (r"\bos\.(system|popen)\s*\(",
     "вызов os.system/os.popen"),
    (r"socket\.(SOCK_RAW|AF_PACKET)",
     "raw-сокеты"),
    (r"\bos\.(setuid|setgid|chroot|fork)\b",
     "понижение/повышение привилегий"),
    (r"\bctypes\.(CDLL|WinDLL|cdll|windll)\b",
     "загрузка нативных библиотек"),
    (r"\b(ptrace|/proc/\d+/(mem|maps|cmdline))\b",
     "обращение к памяти других процессов"),
]

# Flagging "import os.environ" by name is too broad; we deny only direct dumps.
_ENV_DUMP_PATTERNS = [
    r"json\.dumps\s*\(\s*(dict\s*\(\s*)?os\.environ",
]
# Two-token check: presence of `os.environ` together with HTTP-egress libs
# is a strong stealer signal (regardless of which appears first).
_ENV_NAME = re.compile(r"\bos\.environ\b")
_HTTP_NAME = re.compile(r"\b(requests\.(get|post|put)|aiohttp|httpx|urllib\.request|urllib3)\b")

# Suspicious AST imports — block known stealer toolkits.
_DENY_IMPORTS: set[str] = {
    "pyarmor",  # often used for obfuscated stealers
    "uncompyle6",  # decompiler
    "pyminizip",  # not stealer-only, but heavily abused; soft-warn instead?
}


@dataclass(slots=True)
class ValidationResult:
    ok: bool
    error: str | None = None
    warnings: list[str] | None = None


def validate_user_script(source: bytes) -> ValidationResult:
    if len(source) > MAX_FILE_BYTES:
        return ValidationResult(
            ok=False, error=f"Файл слишком большой (>{MAX_FILE_BYTES // 1024} КБ)."
        )

    try:
        text = source.decode("utf-8")
    except UnicodeDecodeError:
        return ValidationResult(ok=False, error="Файл должен быть в кодировке UTF-8.")

    try:
        tree = ast.parse(text)
    except SyntaxError as exc:  # noqa: BLE001 — we want the message
        return ValidationResult(
            ok=False, error=f"Синтаксическая ошибка Python: {exc.msg} (строка {exc.lineno})."
        )

    for pattern, reason in _DENY_PATTERNS:
        if re.search(pattern, text, flags=re.IGNORECASE):
            return ValidationResult(
                ok=False,
                error=f"⛔ Код заблокирован: {reason}. Если это ложное срабатывание — напиши админу.",
            )

    # subprocess + shell-utility heuristic: only flag if both are present.
    has_subprocess = bool(re.search(r"\b(subprocess|Popen|sh\.run|asyncio\.subprocess)\b", text))
    if has_subprocess and re.search(
        r"['\"](?:curl|wget|nc|netcat|ssh|scp|rsync|bash|/bin/sh|/usr/bin/curl)['\"]",
        text,
    ):
        return ValidationResult(
            ok=False,
            error="⛔ Код заблокирован: запуск shell-утилит через subprocess.",
        )
    for pattern in _ENV_DUMP_PATTERNS:
        if re.search(pattern, text):
            return ValidationResult(
                ok=False,
                error="⛔ Код заблокирован: похоже на отправку переменных окружения наружу.",
            )

    if _ENV_NAME.search(text) and _HTTP_NAME.search(text):
        # We additionally require that they appear in the same statement
        # (within ~120 characters of each other) to reduce false positives.
        for m in _ENV_NAME.finditer(text):
            window = text[max(0, m.start() - 200) : m.end() + 200]
            if _HTTP_NAME.search(window):
                return ValidationResult(
                    ok=False,
                    error="⛔ Код заблокирован: возможна утечка os.environ через HTTP.",
                )

    warnings: list[str] = []
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id in _SUSPICIOUS_CALLS
        ):
            warnings.append(
                f"Использование `{node.func.id}` на строке {node.lineno} — потенциальная опасность."
            )
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name.split(".")[0] in _DENY_IMPORTS:
                    return ValidationResult(
                        ok=False,
                        error=f"⛔ Импорт `{alias.name}` запрещён.",
                    )
        if isinstance(node, ast.ImportFrom) and node.module:
            if node.module.split(".")[0] in _DENY_IMPORTS:
                return ValidationResult(
                    ok=False,
                    error=f"⛔ Импорт `{node.module}` запрещён.",
                )

    return ValidationResult(ok=True, warnings=warnings or None)
