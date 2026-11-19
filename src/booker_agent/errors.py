"""Иерархия исключений и их отображение на статусы результата."""

from __future__ import annotations

from typing import Any

from .models import AgentStatus


class BookerError(Exception):
    """Базовая ошибка работы с restful-booker."""

    status: AgentStatus = "server_error"

    def __init__(
        self,
        message: str,
        *,
        http_status: int | None = None,
        details: Any = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.http_status = http_status
        self.details = details


class BookingNotFound(BookerError):
    status: AgentStatus = "not_found"


class AuthError(BookerError):
    status: AgentStatus = "unauthorized"


class BookerValidationError(BookerError):
    status: AgentStatus = "invalid_request"


class ServerError(BookerError):
    status: AgentStatus = "server_error"


class NetworkError(BookerError):
    status: AgentStatus = "network_error"


class ConfigError(BookerError):
    status: AgentStatus = "config_error"
