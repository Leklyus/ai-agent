"""LangChain-инструменты, через которые агент работает с restful-booker."""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any

from langchain_core.tools import BaseTool, tool
from pydantic import BaseModel, Field
from pydantic import ValidationError as PydanticValidationError

from .client import BookerClient
from .errors import BookerError, BookerValidationError
from .models import Booking, BookingDates, BookingUpdate, ToolResult
from .response import format_tool_result

logger = logging.getLogger(__name__)

ConfirmCallback = Callable[[str, dict[str, Any]], bool]


class ListBookingsInput(BaseModel):
    firstname: str | None = Field(
        default=None,
        description="Имя гостя для фильтра. Указывать только при поиске по имени.",
    )
    lastname: str | None = Field(
        default=None,
        description="Фамилия гостя для фильтра. Указывать только при поиске по фамилии.",
    )
    checkin: str | None = Field(
        default=None,
        description="Дата заезда для фильтра в формате YYYY-MM-DD.",
    )
    checkout: str | None = Field(
        default=None,
        description="Дата выезда для фильтра в формате YYYY-MM-DD.",
    )


class GetBookingInput(BaseModel):
    booking_id: int = Field(gt=0, description="Числовой ID бронирования, например 1.")


class CreateBookingInput(BaseModel):
    firstname: str = Field(min_length=1, description="Имя гостя.")
    lastname: str = Field(min_length=1, description="Фамилия гостя.")
    totalprice: int = Field(ge=0, description="Итоговая стоимость в условных единицах.")
    depositpaid: bool = Field(description="Внесена ли предоплата.")
    checkin: str = Field(description="Дата заезда в формате YYYY-MM-DD.")
    checkout: str = Field(description="Дата выезда в формате YYYY-MM-DD, позже даты заезда.")
    additionalneeds: str | None = Field(
        default=None,
        description="Дополнительные пожелания, например Breakfast.",
    )


class UpdateBookingInput(CreateBookingInput):
    booking_id: int = Field(gt=0, description="Числовой ID бронирования, которое нужно заменить.")


class PatchBookingInput(BaseModel):
    booking_id: int = Field(gt=0, description="Числовой ID бронирования.")
    firstname: str | None = Field(default=None, min_length=1, description="Новое имя гостя.")
    lastname: str | None = Field(default=None, min_length=1, description="Новая фамилия гостя.")
    totalprice: int | None = Field(default=None, ge=0, description="Новая итоговая стоимость.")
    depositpaid: bool | None = Field(default=None, description="Новый статус предоплаты.")
    checkin: str | None = Field(default=None, description="Новая дата заезда YYYY-MM-DD.")
    checkout: str | None = Field(default=None, description="Новая дата выезда YYYY-MM-DD.")
    additionalneeds: str | None = Field(
        default=None,
        description="Новые дополнительные пожелания. Пустая строка очищает поле.",
    )


class DeleteBookingInput(BaseModel):
    booking_id: int = Field(gt=0, description="Числовой ID бронирования для удаления.")


def format_validation_error(exc: PydanticValidationError) -> str:
    """Читаемое описание ошибки валидации для модели и пользователя."""
    parts = []
    for error in exc.errors():
        location = ".".join(str(item) for item in error.get("loc", ())) or "arguments"
        parts.append(f"{location}: {error.get('msg', 'invalid value')}")
    return "; ".join(parts)


def _ok(operation: str, data: Any, message: str, http_status: int = 200) -> ToolResult:
    return ToolResult(
        status="success",
        operation=operation,
        http_status=http_status,
        data=data,
        message=message,
    )


def _cancelled(operation: str) -> ToolResult:
    return ToolResult(
        status="invalid_request",
        operation=operation,
        error="Операция отменена пользователем",
        message="Операция отменена пользователем. Не повторяй её без новой просьбы.",
    )


def _confirmed(confirm: ConfirmCallback | None, operation: str, payload: dict[str, Any]) -> bool:
    if confirm is None:
        return True
    try:
        return bool(confirm(operation, payload))
    except Exception:  # pragma: no cover - защита от сбоя интерактивного ввода
        logger.exception("Сбой подтверждения операции %s", operation)
        return False


def _safe_call(operation: str, call: Callable[[], ToolResult]) -> str:
    """Исполнить операцию и вернуть JSON-контракт, не выбрасывая исключений наружу."""
    try:
        result = call()
    except BookerError as exc:
        result = ToolResult(
            status=exc.status,
            operation=operation,
            http_status=exc.http_status,
            error=exc.message,
            message=exc.message,
        )
    except PydanticValidationError as exc:
        result = ToolResult(
            status="invalid_request",
            operation=operation,
            error=format_validation_error(exc),
            message="Аргументы не прошли валидацию. Исправь их и повтори вызов.",
        )
    except Exception as exc:  # pragma: no cover - последняя линия защиты
        logger.exception("Непредвиденная ошибка в инструменте %s", operation)
        result = ToolResult(
            status="server_error",
            operation=operation,
            error=f"Непредвиденная ошибка: {exc}",
            message="Внутренняя ошибка инструмента.",
        )
    return format_tool_result(result)


def build_tools(
    client: BookerClient,
    *,
    confirm: ConfirmCallback | None = None,
) -> list[BaseTool]:
    """Собрать инструменты, привязанные к конкретному клиенту API."""

    @tool("list_bookings", args_schema=ListBookingsInput)
    def list_bookings(
        firstname: str | None = None,
        lastname: str | None = None,
        checkin: str | None = None,
        checkout: str | None = None,
    ) -> str:
        """Вернуть список бронирований.

        Без параметров возвращает все ID. Если указаны firstname и/или lastname,
        API вернёт только совпадающие записи. Даты фильтруют по периоду заезда
        и выезда в формате YYYY-MM-DD. Использовать, когда нужен перечень
        бронирований или поиск по имени и фамилии гостя.
        """

        def call() -> ToolResult:
            data = client.list_bookings(
                firstname=firstname,
                lastname=lastname,
                checkin=checkin,
                checkout=checkout,
            )
            return _ok("list_bookings", data, f"Найдено бронирований: {len(data)}")

        return _safe_call("list_bookings", call)

    @tool("get_booking", args_schema=GetBookingInput)
    def get_booking(booking_id: int) -> str:
        """Получить одно бронирование по числовому ID.

        Возвращает имя гостя, стоимость, признак предоплаты, даты и пожелания.
        Использовать, когда пользователь называет конкретный номер брони.
        """

        def call() -> ToolResult:
            data = client.get_booking(booking_id)
            return _ok("get_booking", data, f"Бронирование {booking_id} получено")

        return _safe_call("get_booking", call)

    @tool("create_booking", args_schema=CreateBookingInput)
    def create_booking(
        firstname: str,
        lastname: str,
        totalprice: int,
        depositpaid: bool,
        checkin: str,
        checkout: str,
        additionalneeds: str | None = None,
    ) -> str:
        """Создать новое бронирование.

        Обязательны имя, фамилия, стоимость, признак предоплаты и обе даты.
        Даты строго в формате YYYY-MM-DD, дата выезда позже даты заезда.
        Использовать только когда пользователь явно просит создать бронирование
        и указал все обязательные данные.
        """

        def call() -> ToolResult:
            booking = Booking(
                firstname=firstname,
                lastname=lastname,
                totalprice=totalprice,
                depositpaid=depositpaid,
                bookingdates=BookingDates(checkin=checkin, checkout=checkout),
                additionalneeds=additionalneeds,
            )
            payload = booking.model_dump(mode="json")
            if not _confirmed(confirm, "create_booking", payload):
                return _cancelled("create_booking")
            created = client.create_booking(booking)
            return _ok(
                "create_booking",
                created.model_dump(mode="json"),
                f"Создано бронирование с ID {created.bookingid}",
            )

        return _safe_call("create_booking", call)

    @tool("update_booking", args_schema=UpdateBookingInput)
    def update_booking(
        booking_id: int,
        firstname: str,
        lastname: str,
        totalprice: int,
        depositpaid: bool,
        checkin: str,
        checkout: str,
        additionalneeds: str | None = None,
    ) -> str:
        """Полностью заменить данные бронирования через PUT.

        Нужен ID и все поля бронирования, иначе незаполненные данные будут
        потеряны. Для изменения одного или двух полей использовать patch_booking.
        """

        def call() -> ToolResult:
            booking = Booking(
                firstname=firstname,
                lastname=lastname,
                totalprice=totalprice,
                depositpaid=depositpaid,
                bookingdates=BookingDates(checkin=checkin, checkout=checkout),
                additionalneeds=additionalneeds,
            )
            payload = {"booking_id": booking_id, **booking.model_dump(mode="json")}
            if not _confirmed(confirm, "update_booking", payload):
                return _cancelled("update_booking")
            data = client.update_booking(booking_id, booking)
            return _ok("update_booking", data, f"Бронирование {booking_id} заменено полностью")

        return _safe_call("update_booking", call)

    @tool("patch_booking", args_schema=PatchBookingInput)
    def patch_booking(
        booking_id: int,
        firstname: str | None = None,
        lastname: str | None = None,
        totalprice: int | None = None,
        depositpaid: bool | None = None,
        checkin: str | None = None,
        checkout: str | None = None,
        additionalneeds: str | None = None,
    ) -> str:
        """Частично обновить бронирование через PATCH.

        Передавать только те поля, которые нужно изменить: имя, фамилию,
        стоимость, предоплату, даты или пожелания. Использовать для запросов
        вида «поставь цену 250 брони 1».
        """

        def call() -> ToolResult:
            if (checkin is None) != (checkout is None):
                raise BookerValidationError(
                    "Для изменения дат нужны обе даты: checkin и checkout в формате YYYY-MM-DD"
                )

            fields: dict[str, Any] = {}
            if firstname is not None:
                fields["firstname"] = firstname
            if lastname is not None:
                fields["lastname"] = lastname
            if totalprice is not None:
                fields["totalprice"] = totalprice
            if depositpaid is not None:
                fields["depositpaid"] = depositpaid
            if checkin is not None or checkout is not None:
                fields["bookingdates"] = {"checkin": checkin, "checkout": checkout}
            if additionalneeds is not None:
                fields["additionalneeds"] = additionalneeds

            update = BookingUpdate.model_validate(fields)
            payload = update.to_payload()
            if not _confirmed(confirm, "patch_booking", {"booking_id": booking_id, **payload}):
                return _cancelled("patch_booking")
            data = client.patch_booking(booking_id, update)
            changed = ", ".join(key for key in payload if key != "bookingdates") or "bookingdates"
            return _ok("patch_booking", data, f"Бронирование {booking_id} обновлено: {changed}")

        return _safe_call("patch_booking", call)

    @tool("delete_booking", args_schema=DeleteBookingInput)
    def delete_booking(booking_id: int) -> str:
        """Удалить бронирование по ID.

        Операция необратима. Использовать только по явной просьбе пользователя.
        """

        def call() -> ToolResult:
            if not _confirmed(confirm, "delete_booking", {"booking_id": booking_id}):
                return _cancelled("delete_booking")
            client.delete_booking(booking_id)
            return _ok(
                "delete_booking",
                {"bookingid": booking_id},
                f"Бронирование {booking_id} удалено",
                http_status=201,
            )

        return _safe_call("delete_booking", call)

    @tool("ping_api")
    def ping_api() -> str:
        """Проверить доступность restful-booker.

        Использовать при жалобах на недоступность API или перед серией операций.
        """

        def call() -> ToolResult:
            client.ping()
            return _ok("ping_api", {"available": True}, "API доступен")

        return _safe_call("ping_api", call)

    return [
        list_bookings,
        get_booking,
        create_booking,
        update_booking,
        patch_booking,
        delete_booking,
        ping_api,
    ]
