"""Доменные модели и контракты результата агента."""

from __future__ import annotations

from datetime import date
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

AgentStatus = Literal[
    "success",
    "not_found",
    "unauthorized",
    "invalid_request",
    "server_error",
    "network_error",
    "needs_clarification",
    "max_steps_reached",
    "config_error",
]


class BookingDates(BaseModel):
    """Даты заезда и выезда."""

    model_config = ConfigDict(extra="ignore")

    checkin: date
    checkout: date

    @model_validator(mode="after")
    def _check_order(self) -> BookingDates:
        if self.checkin >= self.checkout:
            raise ValueError("checkin must be earlier than checkout")
        return self


class Booking(BaseModel):
    """Полное бронирование в формате restful-booker."""

    model_config = ConfigDict(extra="ignore")

    firstname: str = Field(min_length=1, description="Имя гостя")
    lastname: str = Field(min_length=1, description="Фамилия гостя")
    totalprice: int = Field(ge=0, description="Итоговая стоимость")
    depositpaid: bool = Field(description="Признак внесённой предоплаты")
    bookingdates: BookingDates
    additionalneeds: str | None = Field(default=None, description="Дополнительные пожелания")


class BookingUpdate(BaseModel):
    """Частичное обновление бронирования для PATCH."""

    model_config = ConfigDict(extra="forbid")

    firstname: str | None = Field(default=None, min_length=1)
    lastname: str | None = Field(default=None, min_length=1)
    totalprice: int | None = Field(default=None, ge=0)
    depositpaid: bool | None = None
    bookingdates: BookingDates | None = None
    additionalneeds: str | None = None

    @model_validator(mode="after")
    def _require_one_field(self) -> BookingUpdate:
        if not self.model_dump(exclude_none=True):
            raise ValueError("at least one field must be provided")
        return self

    def to_payload(self) -> dict[str, Any]:
        """Только явно переданные поля, даты в ISO-формате."""
        return self.model_dump(mode="json", exclude_none=True)


class BookingCreated(BaseModel):
    """Ответ POST /booking."""

    model_config = ConfigDict(extra="ignore")

    bookingid: int
    booking: Booking


class ToolResult(BaseModel):
    """Единый ответ инструмента, который уходит обратно в модель."""

    status: AgentStatus
    operation: str
    http_status: int | None = None
    data: Any = None
    error: str | None = None
    message: str = ""


class ToolCallTrace(BaseModel):
    """Запись о вызове инструмента в рамках одного запуска агента."""

    tool: str
    args: dict[str, Any] = Field(default_factory=dict)
    status: AgentStatus
    http_status: int | None = None
    error: str | None = None


class AgentResult(BaseModel):
    """Структурированный результат работы агента."""

    status: AgentStatus
    operation: str | None = None
    http_status: int | None = None
    data: Any = None
    summary: str = ""
    tool_calls: list[ToolCallTrace] = Field(default_factory=list)
    error: str | None = None
