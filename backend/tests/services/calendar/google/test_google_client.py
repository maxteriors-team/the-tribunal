"""Unit tests for the Google Calendar API client (mock transport)."""

from __future__ import annotations

import json
from typing import Any

import httpx
import pytest

from app.services.calendar.google.client import (
    GoogleCalendarAuthError,
    GoogleCalendarClient,
    GoogleCalendarError,
)


async def _token() -> str:
    return "ACCESS_TOKEN"


def _client(handler: Any) -> GoogleCalendarClient:
    transport = httpx.MockTransport(handler)
    http_client = httpx.AsyncClient(
        base_url="https://www.googleapis.com/calendar/v3", transport=transport
    )
    return GoogleCalendarClient(_token, "primary", http_client=http_client)


@pytest.mark.asyncio
async def test_insert_event_requests_meet_and_invites() -> None:
    captured: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["auth"] = request.headers.get("authorization")
        captured["body"] = json.loads(request.content)
        return httpx.Response(200, json={"id": "evt_1", "hangoutLink": "https://meet.google.com/x"})

    client = _client(handler)
    result = await client.insert_event(
        summary="Consult",
        start_iso="2099-01-15T15:00:00-05:00",
        end_iso="2099-01-15T15:30:00-05:00",
        timezone="America/New_York",
        attendee_email="a@b.com",
        attendee_name="Alice",
        private_properties={"appointment_id": "42"},
    )

    assert result["id"] == "evt_1"
    assert captured["auth"] == "Bearer ACCESS_TOKEN"
    assert "conferenceDataVersion=1" in captured["url"]
    assert "sendUpdates=all" in captured["url"]
    body = captured["body"]
    assert body["conferenceData"]["createRequest"]["conferenceSolutionKey"]["type"] == (
        "hangoutsMeet"
    )
    assert body["attendees"][0]["email"] == "a@b.com"
    assert body["extendedProperties"]["private"]["appointment_id"] == "42"
    await client.close()


@pytest.mark.asyncio
async def test_freebusy_flattens_busy_blocks() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path.endswith("/freeBusy")
        return httpx.Response(
            200,
            json={
                "calendars": {
                    "primary": {
                        "busy": [
                            {"start": "2099-01-15T15:00:00Z", "end": "2099-01-15T15:30:00Z"},
                        ]
                    }
                }
            },
        )

    client = _client(handler)
    busy = await client.freebusy(
        time_min_iso="2099-01-15T00:00:00Z", time_max_iso="2099-01-16T00:00:00Z"
    )
    assert busy == [{"start": "2099-01-15T15:00:00Z", "end": "2099-01-15T15:30:00Z"}]
    await client.close()


@pytest.mark.asyncio
async def test_delete_event_is_idempotent_on_404() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, json={"error": "gone"})

    client = _client(handler)
    # Should not raise.
    await client.delete_event("missing")
    await client.close()


@pytest.mark.asyncio
async def test_auth_error_maps_to_auth_exception() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"error": "unauthorized"})

    client = _client(handler)
    with pytest.raises(GoogleCalendarAuthError):
        await client.get_event("evt")
    await client.close()


@pytest.mark.asyncio
async def test_server_error_maps_to_generic_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, json={"error": "boom"})

    client = _client(handler)
    with pytest.raises(GoogleCalendarError):
        await client.get_event("evt")
    await client.close()
