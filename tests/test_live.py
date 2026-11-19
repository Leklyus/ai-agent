"""Live-проверки против реального restful-booker.

Запуск: RUN_LIVE=1 pytest -m live
"""

from __future__ import annotations

import os

import pytest

from booker_agent.client import BookerClient
from booker_agent.config import Settings
from booker_agent.errors import BookingNotFound
from booker_agent.models import Booking, BookingDates, BookingUpdate

pytestmark = [
    pytest.mark.live,
    pytest.mark.skipif(
        os.getenv("RUN_LIVE") != "1",
        reason="Установите RUN_LIVE=1, чтобы выполнять запросы к реальному API",
    ),
]


def test_live_crud_cycle() -> None:
    settings = Settings()
    booking = Booking(
        firstname="Maria",
        lastname="Ivanova",
        totalprice=150,
        depositpaid=True,
        bookingdates=BookingDates(checkin="2026-12-01", checkout="2026-12-05"),
        additionalneeds="Breakfast",
    )

    with BookerClient(settings) as client:
        assert client.ping()

        bookings = client.list_bookings()
        assert bookings and "bookingid" in bookings[0]
        assert client.list_bookings(firstname="Sally", lastname="Brown") is not None

        created = client.create_booking(booking)
        try:
            fetched = client.get_booking(created.bookingid)
            assert fetched["firstname"] == "Maria"
            assert fetched["bookingdates"]["checkin"] == "2026-12-01"

            updated = client.patch_booking(created.bookingid, BookingUpdate(totalprice=250))
            assert updated["totalprice"] == 250
        finally:
            client.delete_booking(created.bookingid)

        with pytest.raises(BookingNotFound):
            client.get_booking(created.bookingid)
