"""Единый текстовый формат ответа всех инструментов.

Формат:

    Status: success | error
    Action: <описание действия>
    Data: <результат API в JSON>
    Errors: <описание ошибки или none>

Внутри приложения статус остаётся детальным (`not_found`, `unauthorized`,
`invalid_request`, `server_error`, `network_error`), а в тексте он кодируется
в строке `Errors` как `<код>: <сообщение>`, чтобы агент мог восстановить
точный статус для `AgentResult`.
"""

from __future__ import annotations

import json
import re
from typing import Any

from .models import AgentStatus, ToolResult

_FIELD_RE = re.compile(r"^(Status|Action|Data|Errors):\s?(.*)$")
_HTTP_RE = re.compile(r"HTTP\s+(\d{3})")
_HTTP_SUFFIX_RE = re.compile(r"\s*\(HTTP\s+\d{3}\)")
_ERROR_CODES = (
    "not_found",
    "unauthorized",
    "invalid_request",
    "server_error",
    "network_error",
    "config_error",
)


def format_tool_result(result: ToolResult) -> str:
    """Сериализовать результат инструмента в фиксированный текстовый формат."""
    status = "success" if result.status == "success" else "error"

    action = f"{result.operation}: {result.message or 'операция выполнена'}"
    if result.http_status is not None:
        action = f"{action} (HTTP {result.http_status})"

    if result.data is None:
        data = "null"
    else:
        data = json.dumps(result.data, ensure_ascii=False, separators=(",", ":"), default=str)

    if result.status == "success":
        errors = "none"
    else:
        detail = result.error or result.message or "неизвестная ошибка"
        errors = f"{result.status}: {detail}"

    return f"Status: {status}\nAction: {action}\nData: {data}\nErrors: {errors}"


def parse_tool_result(text: str, *, operation: str) -> ToolResult:
    """Разобрать текстовый ответ инструмента обратно в `ToolResult`."""
    fields: dict[str, list[str]] = {}
    current: str | None = None

    for line in text.splitlines():
        match = _FIELD_RE.match(line)
        if match:
            current = match.group(1)
            fields.setdefault(current, []).append(match.group(2))
        elif current:
            fields[current].append(line)

    status_line = " ".join(fields.get("Status", [])).strip().lower()
    action = " ".join(fields.get("Action", [])).strip()
    data_raw = "\n".join(fields.get("Data", [])).strip()
    errors = "\n".join(fields.get("Errors", [])).strip()

    http_status: int | None = None
    http_match = _HTTP_RE.search(action) or _HTTP_RE.search(errors)
    if http_match:
        http_status = int(http_match.group(1))

    status: AgentStatus = "success" if status_line == "success" else "server_error"
    error: str | None = None

    if status_line != "success":
        code, separator, remainder = errors.partition(":")
        code = code.strip()
        if separator and code in _ERROR_CODES:
            status = code  # type: ignore[assignment]
            error = remainder.strip() or errors
        else:
            error = errors or "неизвестная ошибка"

    data: Any = None
    if data_raw and data_raw.lower() not in {"null", "none"}:
        try:
            data = json.loads(data_raw)
        except ValueError:
            data = data_raw

    message = action
    prefix = f"{operation}: "
    if message.startswith(prefix):
        message = message[len(prefix) :]
    message = _HTTP_SUFFIX_RE.sub("", message).strip()

    return ToolResult(
        status=status,
        operation=operation,
        http_status=http_status,
        data=data,
        error=error,
        message=message,
    )
