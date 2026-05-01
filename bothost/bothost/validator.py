"""Sanity checks for user-submitted Python files before we run them."""

from __future__ import annotations

import ast
from dataclasses import dataclass

MAX_FILE_BYTES = 1 * 1024 * 1024  # 1 MiB

# These are reported as warnings, not blockers — the user might legitimately
# need network access (Telegram API itself uses HTTPS).
_SUSPICIOUS_CALLS: set[str] = {
    "eval",
    "exec",
    "compile",
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

    return ValidationResult(ok=True, warnings=warnings or None)
