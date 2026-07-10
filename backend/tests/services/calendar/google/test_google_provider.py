"""Unit tests for GoogleCalendarProvider (fake Google client)."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

import pytest

from app.services.calendar.google.availability import resolve_schedule_config
from app.services.calendar.google.client import GoogleCalendarError
from app.services.calendar.google.provider import GoogleCalendarProvider


class _FakeClient:
    def __init__(self, busy: list[dict[str, str]] | None = None) -> None:
        self.busy = busy or []
        self.inserted: dict[str, Any] | None = None
        self.patched: dict[str, Any] | None = None
        self.deleted: str | None = None
        self.closed = False

    async def freebusy(self, **_kwargs: Any) -> list[dict[str, str]]:
        return self.busy

    async def insert_event(self, **kwargs: Any) -> dict[str, Any]:
        self.inserted = kwargs
        return {"id": "evt_new", "hangoutLink": "https://meet.google.com/x"}

    async def patch_event(self, event_id: str, **kwargs: Any) -> dict[str, Any]:
        self.patched = {"event_id": event_id, **kwargs}
        return {"id": event_id}

    async def delete_event(self, event_id: str) -> None:
        self.deleted = event_id

    async def close(self) -> None:
        self.closed = True


def _provider(client: _FakeClient) -> GoogleCalendarProvider:
    # Wide horizon so the deterministic far-future (2099) fixture dates are not
    # trimmed by the booking-horizon guard (which is measured from real now).
    schedule = resolve_schedule_config(
        {
            "timezone": "America/New_York",
            "slot_duration_minutes": 30,
            "max_horizon_days": 1_000_000,
        }
    )
    return GoogleCalendarProvider(client, schedule)  # type: ignore[arg-type]


@pytest.mark.asyncio
async def test_get_availability_uses_engine_and_freebusy() -> None:
    client = _FakeClient(busy=[{"start": "2099-01-14T14:30:00Z", "end": "2099-01-14T15:00:00Z"}])
    provider = _provider(client)
    wed = datetime(2099, 1, 14, tzinfo=ZoneInfo("America/New_York"))
    slots = await provider.get_availability(wed, wed)
    times = [s["time"] for s in slots]
    # 09:30 EST (14:30Z) removed by the busy block.
    assert "09:30" not in times
    assert "09:00" in times


@pytest.mark.asyncio
async def test_create_booking_inserts_event_with_meet() -> None:
    client = _FakeClient(busy=[])
    provider = _provider(client)
    booking = await provider.create_booking(
        start_time_iso="2099-01-14T09:00:00-05:00",
        contact_email="a@b.com",
        contact_name="Alice",
        duration_minutes=30,
        metadata={"notes": "bring docs"},
        phone_number="+15551234567",
    )
    assert booking.provider == "google"
    assert booking.external_event_id == "evt_new"
    assert client.inserted is not None
    assert client.inserted["add_meet"] is True
    assert client.inserted["description"] == "bring docs"
    assert client.inserted["private_properties"]["attendee_phone"] == "+15551234567"


@pytest.mark.asyncio
async def test_create_booking_localizes_text_channel_walltime() -> None:
    # The text channel reconstructs a naive ``...Z`` ISO from the local HH:MM the
    # slot engine returned. The provider must anchor that wall-clock to the
    # schedule timezone (America/New_York = -05:00 in January), not book it as
    # UTC (which would be off by the offset).
    client = _FakeClient(busy=[])
    provider = _provider(client)
    await provider.create_booking(
        start_time_iso="2099-01-14T09:00:00.000Z",
        contact_email="a@b.com",
        contact_name="Alice",
        duration_minutes=30,
    )
    assert client.inserted is not None
    assert client.inserted["start_iso"] == "2099-01-14T09:00:00-05:00"
    assert client.inserted["end_iso"] == "2099-01-14T09:30:00-05:00"


@pytest.mark.asyncio
async def test_create_booking_rejects_when_slot_now_busy() -> None:
    client = _FakeClient(busy=[{"start": "2099-01-14T14:00:00Z", "end": "2099-01-14T14:30:00Z"}])
    provider = _provider(client)
    with pytest.raises(GoogleCalendarError):
        await provider.create_booking(
            start_time_iso="2099-01-14T09:00:00-05:00",
            contact_email="a@b.com",
            contact_name="Alice",
        )
    assert client.inserted is None


@pytest.mark.asyncio
async def test_cancel_and_reschedule() -> None:
    client = _FakeClient()
    provider = _provider(client)
    assert await provider.cancel_booking("evt_1") is True
    assert client.deleted == "evt_1"

    rebooked = await provider.reschedule_booking(
        "evt_1", start_time_iso="2099-01-14T10:00:00-05:00", duration_minutes=45
    )
    assert rebooked.external_event_id == "evt_1"
    assert client.patched is not None
    assert client.patched["event_id"] == "evt_1"
