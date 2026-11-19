"""HTTP-клиент restful-booker: авторизация, кэш токена, retry и маппинг ошибок."""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Mapping
from datetime import date
from typing import Any

import httpx
from pydantic import ValidationError

from .config import Settings
from .errors import (
    AuthError,
    BookerError,
    BookerValidationError,
    BookingNotFound,
    NetworkError,
    ServerError,
)
from .models import Booking, BookingCreated, BookingUpdate

logger = logging.getLogger(__name__)

RETRY_STATUSES = frozenset({429, 502, 503, 504})
TOKEN_TTL_SECONDS = 9 * 60


def _iso(value: date | str | None) -> str | None:
    if value is None:
        return None
    return value.isoformat() if isinstance(value, date) else value


def _extract_detail(response: httpx.Response) -> str:
    text = (response.text or "").strip().replace("\n", " ")
    return text[:200]


def _error_from_response(response: httpx.Response, operation: str) -> BookerError:
    status = response.status_code
    detail = _extract_detail(response)
    if status == 404:
        return BookingNotFound("Бронирование с указанным ID не найдено", http_status=status)
    if status in (401, 403):
        return AuthError("Доступ запрещён: токен отсутствует или недействителен", http_status=status)
    if status in (400, 405, 422):
        return BookerValidationError(
            f"API отклонил запрос ({operation}): {detail or 'нет деталей'}", http_status=status
        )
    if status >= 500:
        return ServerError(f"Ошибка на стороне restful-booker: HTTP {status}", http_status=status)
    return BookerError(
        f"Неожиданный ответ API ({operation}): HTTP {status} {detail}".strip(), http_status=status
    )


class BookerClient:
    """Тонкая обёртка над restful-booker с явным контролем ошибок."""

    def __init__(self, settings: Settings, *, transport: httpx.BaseTransport | None = None) -> None:
        self._settings = settings
        self._token: str | None = None
        self._token_expires_at = 0.0
        self._token_lock = threading.Lock()
        self._http = httpx.Client(
            base_url=settings.booker_base_url.rstrip("/"),
            timeout=settings.booker_timeout,
            transport=transport,
            headers={"Accept": "application/json"},
        )

    # --- публичные операции ---

    def list_bookings(
        self,
        firstname: str | None = None,
        lastname: str | None = None,
        checkin: date | str | None = None,
        checkout: date | str | None = None,
    ) -> list[dict[str, Any]]:
        """Список бронирований; фильтры передаются только если заданы."""
        params: dict[str, str] = {}
        if firstname:
            params["firstname"] = firstname
        if lastname:
            params["lastname"] = lastname
        if checkin is not None:
            params["checkin"] = str(_iso(checkin))
        if checkout is not None:
            params["checkout"] = str(_iso(checkout))

        response = self._request("GET", "/booking", params=params or None)
        data = self._handle(response, operation="list_bookings")
        if not isinstance(data, list):
            raise ServerError(
                "Неожиданный формат ответа: ожидался список бронирований",
                http_status=response.status_code,
            )
        return data

    def get_booking(self, booking_id: int) -> dict[str, Any]:
        """Одно бронирование по ID."""
        self._ensure_id(booking_id)
        response = self._request("GET", f"/booking/{booking_id}")
        data = self._handle(response, operation="get_booking")
        if not isinstance(data, dict):
            raise ServerError(
                "Неожиданный формат ответа: ожидался объект бронирования",
                http_status=response.status_code,
            )
        return data

    def create_booking(self, booking: Booking) -> BookingCreated:
        """Создание бронирования. API отвечает 200, поэтому 201 тоже принимаем."""
        response = self._request("POST", "/booking", payload=booking.model_dump(mode="json"))
        data = self._handle(response, operation="create_booking", allowed=(200, 201))
        try:
            return BookingCreated.model_validate(data)
        except ValidationError as exc:
            raise ServerError(
                f"Неожиданный формат ответа при создании бронирования: {exc.error_count()} ошибок",
                http_status=response.status_code,
            ) from exc

    def update_booking(self, booking_id: int, booking: Booking) -> dict[str, Any]:
        """Полное обновление бронирования через PUT."""
        self._ensure_id(booking_id)
        response = self._request(
            "PUT",
            f"/booking/{booking_id}",
            payload=booking.model_dump(mode="json"),
            auth=True,
        )
        data = self._handle(response, operation="update_booking")
        if not isinstance(data, dict):
            raise ServerError("Неожиданный формат ответа при обновлении", http_status=response.status_code)
        return data

    def patch_booking(
        self,
        booking_id: int,
        update: BookingUpdate | Mapping[str, Any],
    ) -> dict[str, Any]:
        """Частичное обновление: в теле только переданные поля."""
        self._ensure_id(booking_id)
        payload = update.to_payload() if isinstance(update, BookingUpdate) else dict(update)
        if not payload:
            raise BookerValidationError("Не передано ни одного поля для обновления")
        response = self._request("PATCH", f"/booking/{booking_id}", payload=payload, auth=True)
        data = self._handle(response, operation="patch_booking")
        if not isinstance(data, dict):
            raise ServerError(
                "Неожиданный формат ответа при частичном обновлении",
                http_status=response.status_code,
            )
        return data

    def delete_booking(self, booking_id: int) -> None:
        """Удаление бронирования. Успехом считается 200, 201 и 204."""
        self._ensure_id(booking_id)
        response = self._request("DELETE", f"/booking/{booking_id}", auth=True)
        self._handle(response, operation="delete_booking", allowed=(200, 201, 204), parse_json=False)

    def ping(self) -> bool:
        """Health-check API, полезен при холодном старте Heroku."""
        response = self._request("GET", "/ping")
        self._handle(response, operation="ping_api", allowed=(200, 201), parse_json=False)
        return True

    # --- служебные методы ---

    @staticmethod
    def _ensure_id(booking_id: int) -> None:
        if not isinstance(booking_id, int) or isinstance(booking_id, bool) or booking_id <= 0:
            raise BookerValidationError(
                f"ID бронирования должен быть положительным целым числом, получено: {booking_id!r}"
            )

    def _request(
        self,
        method: str,
        path: str,
        *,
        params: Mapping[str, Any] | None = None,
        payload: Any = None,
        auth: bool = False,
    ) -> httpx.Response:
        headers: dict[str, str] = {}
        if auth:
            headers["Cookie"] = f"token={self._get_token()}"

        response = self._send(method, path, headers=headers, params=params, payload=payload)

        if auth and response.status_code in (401, 403):
            logger.info("Токен отклонён с кодом %s, обновляю и повторяю запрос", response.status_code)
            headers["Cookie"] = f"token={self._get_token(force_refresh=True)}"
            response = self._send(method, path, headers=headers, params=params, payload=payload)

        return response

    def _send(
        self,
        method: str,
        path: str,
        *,
        headers: Mapping[str, str] | None = None,
        params: Mapping[str, Any] | None = None,
        payload: Any = None,
    ) -> httpx.Response:
        attempts = max(1, self._settings.booker_max_retries + 1)
        request_headers = {"Accept": "application/json", **dict(headers or {})}
        last_error: Exception | None = None

        for attempt in range(attempts):
            try:
                response = self._http.request(
                    method,
                    path,
                    headers=request_headers,
                    params=params,
                    json=payload,
                )
            except httpx.TimeoutException as exc:
                last_error = exc
                logger.warning(
                    "Таймаут %s %s, попытка %d из %d", method, path, attempt + 1, attempts
                )
            except httpx.HTTPError as exc:
                raise NetworkError(f"Ошибка соединения с restful-booker: {exc}") from exc
            else:
                if response.status_code in RETRY_STATUSES and attempt + 1 < attempts:
                    logger.warning(
                        "Ответ %s на %s %s, повтор через %.1f с",
                        response.status_code,
                        method,
                        path,
                        self._backoff(attempt),
                    )
                else:
                    return response

            if attempt + 1 < attempts:
                time.sleep(self._backoff(attempt))

        raise NetworkError(
            f"Не удалось выполнить {method} {path}: {last_error}", details=str(last_error)
        )

    @staticmethod
    def _backoff(attempt: int) -> float:
        return 0.5 * (2**attempt)

    def _get_token(self, force_refresh: bool = False) -> str:
        """OAuth-токен restful-booker с кэшем в памяти и TTL."""
        with self._token_lock:
            now = time.monotonic()
            if not force_refresh and self._token and now < self._token_expires_at:
                return self._token

            response = self._send(
                "POST",
                "/auth",
                payload={
                    "username": self._settings.booker_username,
                    "password": self._settings.booker_password,
                },
            )
            if response.status_code not in (200, 201):
                raise AuthError(
                    f"Не удалось авторизоваться в restful-booker: HTTP {response.status_code}",
                    http_status=response.status_code,
                )
            try:
                token = response.json().get("token")
            except ValueError as exc:
                raise AuthError("Ответ авторизации не содержит JSON") from exc
            if not token:
                raise AuthError("Ответ авторизации не содержит токен")

            self._token = token
            self._token_expires_at = now + TOKEN_TTL_SECONDS
            return token

    @staticmethod
    def _handle(
        response: httpx.Response,
        *,
        operation: str,
        allowed: tuple[int, ...] = (200,),
        parse_json: bool = True,
    ) -> Any:
        if response.status_code in allowed:
            if not parse_json or not response.content:
                return None
            try:
                return response.json()
            except ValueError as exc:
                raise ServerError(
                    f"Некорректный JSON в ответе API ({operation})",
                    http_status=response.status_code,
                ) from exc
        raise _error_from_response(response, operation)

    def close(self) -> None:
        self._http.close()

    def __enter__(self) -> BookerClient:
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()
