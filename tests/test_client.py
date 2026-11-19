"""Тесты HTTP-клиента на respx: контракты, авторизация, retry."""

from __future__ import annotations

import json

import httpx
import pytest
import respx

from booker_agent.client import BookerClient
from booker_agent.errors import (
    BookerValidationError,
    BookingNotFound,
    NetworkError,
    ServerError,
)
from booker_agent.models import Booking, BookingUpdate

BASE_URL = "https://restful-booker.herokuapp.com"
AUTH_URL = f"{BASE_URL}/auth"


def make_booking(payload: dict) -> Booking:
    return Booking.model_validate(payload)


@respx.mock
def test_list_bookings_returns_ids(client: BookerClient) -> None:
    route = respx.get(f"{BASE_URL}/booking").mock(
        return_value=httpx.Response(200, json=[{"bookingid": 1}, {"bookingid": 2}])
    )

    assert client.list_bookings() == [{"bookingid": 1}, {"bookingid": 2}]
    request = route.calls[0].request
    assert request.headers["Accept"] == "application/json"
    assert dict(request.url.params) == {}


@respx.mock
def test_list_bookings_passes_filters(client: BookerClient) -> None:
    route = respx.get(f"{BASE_URL}/booking").mock(
        return_value=httpx.Response(200, json=[{"bookingid": 3}])
    )

    client.list_bookings(firstname="Sally", lastname="Brown")

    assert dict(route.calls[0].request.url.params) == {
        "firstname": "Sally",
        "lastname": "Brown",
    }


@respx.mock
def test_get_booking_uses_json_accept(client: BookerClient, booking_payload: dict) -> None:
    route = respx.get(f"{BASE_URL}/booking/1").mock(
        return_value=httpx.Response(200, json=booking_payload)
    )

    data = client.get_booking(1)

    assert data["firstname"] == "Sally"
    assert route.calls[0].request.headers["Accept"] == "application/json"


@respx.mock
def test_get_booking_not_found(client: BookerClient) -> None:
    respx.get(f"{BASE_URL}/booking/999").mock(return_value=httpx.Response(404, text="Not Found"))

    with pytest.raises(BookingNotFound) as error:
        client.get_booking(999)

    assert error.value.http_status == 404


@respx.mock
def test_server_error_mapping(client: BookerClient) -> None:
    respx.get(f"{BASE_URL}/booking/1").mock(return_value=httpx.Response(500, text="oops"))

    with pytest.raises(ServerError) as error:
        client.get_booking(1)

    assert error.value.http_status == 500


def test_get_booking_rejects_invalid_id(client: BookerClient) -> None:
    with pytest.raises(BookerValidationError):
        client.get_booking(0)


@respx.mock
def test_create_booking(client: BookerClient, booking_payload: dict) -> None:
    respx.post(f"{BASE_URL}/booking").mock(
        return_value=httpx.Response(200, json={"bookingid": 42, "booking": booking_payload})
    )

    created = client.create_booking(make_booking(booking_payload))

    assert created.bookingid == 42
    assert created.booking.firstname == "Sally"


@respx.mock
def test_update_booking_uses_put_and_token(client: BookerClient, booking_payload: dict) -> None:
    respx.post(AUTH_URL).mock(return_value=httpx.Response(200, json={"token": "secret"}))
    route = respx.put(f"{BASE_URL}/booking/1").mock(
        return_value=httpx.Response(200, json=booking_payload)
    )

    result = client.update_booking(1, make_booking(booking_payload))

    assert result["lastname"] == "Brown"
    request = route.calls[0].request
    assert request.method == "PUT"
    assert request.headers["Cookie"] == "token=secret"


@respx.mock
def test_patch_booking_sends_only_provided_fields(client: BookerClient) -> None:
    auth_route = respx.post(AUTH_URL).mock(return_value=httpx.Response(200, json={"token": "secret"}))
    patch_route = respx.patch(f"{BASE_URL}/booking/1").mock(
        return_value=httpx.Response(200, json={"totalprice": 250})
    )

    result = client.patch_booking(1, BookingUpdate(totalprice=250))

    assert result["totalprice"] == 250
    assert auth_route.call_count == 1
    request = patch_route.calls[0].request
    assert request.headers["Cookie"] == "token=secret"
    assert json.loads(request.content) == {"totalprice": 250}


@respx.mock
def test_patch_booking_rejects_empty_update(client: BookerClient) -> None:
    with pytest.raises(BookerValidationError):
        client.patch_booking(1, {})


@respx.mock
def test_token_is_cached_between_requests(client: BookerClient) -> None:
    auth_route = respx.post(AUTH_URL).mock(return_value=httpx.Response(200, json={"token": "secret"}))
    respx.patch(f"{BASE_URL}/booking/1").mock(return_value=httpx.Response(200, json={}))

    client.patch_booking(1, {"totalprice": 100})
    client.patch_booking(1, {"totalprice": 150})

    assert auth_route.call_count == 1


@respx.mock
def test_patch_refreshes_token_on_forbidden(client: BookerClient) -> None:
    auth_route = respx.post(AUTH_URL).mock(
        side_effect=[
            httpx.Response(200, json={"token": "old"}),
            httpx.Response(200, json={"token": "new"}),
        ]
    )
    patch_route = respx.patch(f"{BASE_URL}/booking/1").mock(
        side_effect=[
            httpx.Response(403, text="Forbidden"),
            httpx.Response(200, json={"totalprice": 250}),
        ]
    )

    result = client.patch_booking(1, {"totalprice": 250})

    assert result == {"totalprice": 250}
    assert auth_route.call_count == 2
    assert patch_route.calls[0].request.headers["Cookie"] == "token=old"
    assert patch_route.calls[1].request.headers["Cookie"] == "token=new"


@respx.mock
def test_delete_booking_accepts_created_status(client: BookerClient) -> None:
    respx.post(AUTH_URL).mock(return_value=httpx.Response(200, json={"token": "secret"}))
    route = respx.delete(f"{BASE_URL}/booking/1").mock(
        return_value=httpx.Response(201, text="Created")
    )

    client.delete_booking(1)

    assert route.calls[0].request.headers["Cookie"] == "token=secret"


@respx.mock
def test_retries_on_temporary_server_error(settings, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("booker_agent.client.time.sleep", lambda *_: None)
    retry_settings = settings.model_copy(update={"booker_max_retries": 1})

    with BookerClient(retry_settings) as retry_client:
        route = respx.get(f"{BASE_URL}/booking").mock(
            side_effect=[
                httpx.Response(503, text="busy"),
                httpx.Response(200, json=[{"bookingid": 1}]),
            ]
        )

        assert retry_client.list_bookings() == [{"bookingid": 1}]
        assert route.call_count == 2


@respx.mock
def test_timeout_maps_to_network_error(client: BookerClient) -> None:
    respx.get(f"{BASE_URL}/booking").mock(side_effect=httpx.TimeoutException("boom"))

    with pytest.raises(NetworkError):
        client.list_bookings()


@respx.mock
def test_ping_accepts_created(client: BookerClient) -> None:
    respx.get(f"{BASE_URL}/ping").mock(return_value=httpx.Response(201, text="Created"))

    assert client.ping() is True
