"""Общие фикстуры тестов."""

from __future__ import annotations

from collections.abc import Iterator

import pytest

from booker_agent.client import BookerClient
from booker_agent.config import Settings

BASE_URL = "https://restful-booker.herokuapp.com"


@pytest.fixture
def settings() -> Settings:
    return Settings(
        _env_file=None,
        gigachat_credentials="test-credentials",
        booker_base_url=BASE_URL,
        booker_timeout=5.0,
        booker_max_retries=0,
        agent_max_steps=6,
    )


@pytest.fixture
def client(settings: Settings) -> Iterator[BookerClient]:
    with BookerClient(settings) as instance:
        yield instance


@pytest.fixture
def booking_payload() -> dict:
    return {
        "firstname": "Sally",
        "lastname": "Brown",
        "totalprice": 111,
        "depositpaid": True,
        "bookingdates": {"checkin": "2026-12-01", "checkout": "2026-12-05"},
        "additionalneeds": "Breakfast",
    }
