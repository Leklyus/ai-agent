"""Тесты инструментов: формат ответа, валидация и подтверждение мутаций."""

from __future__ import annotations

import json

import httpx
import pytest
import respx
from pydantic import ValidationError

from booker_agent.client import BookerClient
from booker_agent.response import parse_tool_result
from booker_agent.tools import build_tools

BASE_URL = "https://restful-booker.herokuapp.com"
AUTH_URL = f"{BASE_URL}/auth"


def tools_by_name(client: BookerClient, **kwargs) -> dict:
    return {tool.name: tool for tool in build_tools(client, **kwargs)}


def call_tool(
    client: BookerClient,
    name: str,
    arguments: dict | None = None,
    **kwargs,
):
    """Вызвать инструмент и вернуть сырой текст ответа плюс разобранный ToolResult."""
    raw = tools_by_name(client, **kwargs)[name].invoke(arguments or {})
    return raw, parse_tool_result(raw, operation=name)


@respx.mock
def test_list_bookings_tool(client: BookerClient) -> None:
    respx.get(f"{BASE_URL}/booking").mock(
        return_value=httpx.Response(200, json=[{"bookingid": 1}, {"bookingid": 2}])
    )

    _, payload = call_tool(client, "list_bookings")

    assert payload.status == "success"
    assert payload.operation == "list_bookings"
    assert payload.http_status == 200
    assert payload.data == [{"bookingid": 1}, {"bookingid": 2}]
    assert "2" in payload.message


@respx.mock
def test_tool_response_uses_fixed_format(client: BookerClient) -> None:
    respx.get(f"{BASE_URL}/booking").mock(
        return_value=httpx.Response(200, json=[{"bookingid": 1}])
    )

    raw, _ = call_tool(client, "list_bookings")

    assert raw.splitlines() == [
        "Status: success",
        "Action: list_bookings: Найдено бронирований: 1 (HTTP 200)",
        'Data: [{"bookingid":1}]',
        "Errors: none",
    ]


@respx.mock
def test_tool_error_response_uses_fixed_format(client: BookerClient) -> None:
    respx.get(f"{BASE_URL}/booking/999").mock(return_value=httpx.Response(404, text="Not Found"))

    raw, payload = call_tool(client, "get_booking", {"booking_id": 999})
    lines = raw.splitlines()

    assert lines[0] == "Status: error"
    assert lines[1] == "Action: get_booking: Бронирование с указанным ID не найдено (HTTP 404)"
    assert lines[2] == "Data: null"
    assert lines[3].startswith("Errors: not_found: ")
    assert payload.status == "not_found"
    assert payload.http_status == 404


@respx.mock
def test_list_bookings_tool_with_filter(client: BookerClient) -> None:
    route = respx.get(f"{BASE_URL}/booking").mock(
        return_value=httpx.Response(200, json=[{"bookingid": 5}])
    )

    _, payload = call_tool(
        client,
        "list_bookings",
        {"firstname": "Sally", "lastname": "Brown"},
    )

    assert payload.status == "success"
    assert dict(route.calls[0].request.url.params) == {
        "firstname": "Sally",
        "lastname": "Brown",
    }


@respx.mock
def test_get_booking_tool_not_found(client: BookerClient) -> None:
    respx.get(f"{BASE_URL}/booking/999").mock(return_value=httpx.Response(404, text="Not Found"))

    _, payload = call_tool(client, "get_booking", {"booking_id": 999})

    assert payload.status == "not_found"
    assert payload.http_status == 404
    assert payload.data is None
    assert payload.error


@respx.mock
def test_create_booking_tool(client: BookerClient) -> None:
    booking = {
        "firstname": "Maria",
        "lastname": "Ivanova",
        "totalprice": 150,
        "depositpaid": True,
        "bookingdates": {"checkin": "2026-12-01", "checkout": "2026-12-05"},
        "additionalneeds": "Breakfast",
    }
    respx.post(f"{BASE_URL}/booking").mock(
        return_value=httpx.Response(200, json={"bookingid": 7, "booking": booking})
    )

    _, payload = call_tool(
        client,
        "create_booking",
        {
            "firstname": "Maria",
            "lastname": "Ivanova",
            "totalprice": 150,
            "depositpaid": True,
            "checkin": "2026-12-01",
            "checkout": "2026-12-05",
            "additionalneeds": "Breakfast",
        },
    )

    assert payload.status == "success"
    assert payload.data["bookingid"] == 7
    assert payload.data["booking"]["firstname"] == "Maria"


def test_create_booking_tool_rejects_invalid_dates(client: BookerClient) -> None:
    raw, payload = call_tool(
        client,
        "create_booking",
        {
            "firstname": "Maria",
            "lastname": "Ivanova",
            "totalprice": 150,
            "depositpaid": True,
            "checkin": "2026-12-10",
            "checkout": "2026-12-01",
        },
    )

    assert payload.status == "invalid_request"
    assert raw.splitlines()[0] == "Status: error"
    assert raw.splitlines()[3].startswith("Errors: invalid_request: ")
    assert "earlier" in payload.error


@respx.mock
def test_patch_booking_tool_sends_only_changed_fields(client: BookerClient) -> None:
    respx.post(AUTH_URL).mock(return_value=httpx.Response(200, json={"token": "secret"}))
    route = respx.patch(f"{BASE_URL}/booking/1").mock(
        return_value=httpx.Response(200, json={"totalprice": 250})
    )

    _, payload = call_tool(client, "patch_booking", {"booking_id": 1, "totalprice": 250})

    assert payload.status == "success"
    assert payload.data["totalprice"] == 250
    assert json.loads(route.calls[0].request.content) == {"totalprice": 250}


def test_patch_booking_tool_requires_both_dates(client: BookerClient) -> None:
    raw, payload = call_tool(client, "patch_booking", {"booking_id": 1, "checkin": "2026-12-01"})

    assert payload.status == "invalid_request"
    assert "обе даты" in payload.error
    assert "Errors: invalid_request:" in raw


def test_patch_booking_tool_rejects_empty_payload(client: BookerClient) -> None:
    _, payload = call_tool(client, "patch_booking", {"booking_id": 1})

    assert payload.status == "invalid_request"


@respx.mock
def test_delete_booking_tool(client: BookerClient) -> None:
    respx.post(AUTH_URL).mock(return_value=httpx.Response(200, json={"token": "secret"}))
    respx.delete(f"{BASE_URL}/booking/1").mock(return_value=httpx.Response(201, text="Created"))

    _, payload = call_tool(client, "delete_booking", {"booking_id": 1})

    assert payload.status == "success"
    assert payload.http_status == 201


def test_confirm_callback_blocks_delete(client: BookerClient) -> None:
    raw, payload = call_tool(
        client,
        "delete_booking",
        {"booking_id": 1},
        confirm=lambda operation, payload: False,
    )

    assert payload.status == "invalid_request"
    assert "отменена" in payload.error
    assert "Errors: invalid_request:" in raw


@respx.mock
def test_ping_tool(client: BookerClient) -> None:
    respx.get(f"{BASE_URL}/ping").mock(return_value=httpx.Response(201, text="Created"))

    _, payload = call_tool(client, "ping_api")

    assert payload.status == "success"
    assert payload.data == {"available": True}


def test_all_tools_have_descriptions(client: BookerClient) -> None:
    tools = build_tools(client)

    assert len(tools) == 7
    for item in tools:
        assert item.description, f"У инструмента {item.name} нет описания"
        assert isinstance(item.args, dict)


@pytest.mark.parametrize(
    ("tool_name", "arguments"),
    [
        ("get_booking", {"booking_id": 0}),
        ("delete_booking", {"booking_id": -1}),
        ("create_booking", {"firstname": "Maria"}),
    ],
)
def test_tools_reject_invalid_arguments(client: BookerClient, tool_name: str, arguments: dict) -> None:
    with pytest.raises(ValidationError):
        tools_by_name(client)[tool_name].invoke(arguments)
