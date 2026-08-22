"""Unit tests for per-user Google Calendar OAuth and scheduling helpers."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services import google_calendar
from app.services.google_calendar import GoogleCalendarError


@pytest.mark.asyncio
async def test_authorization_url_uses_offline_access_and_one_time_state() -> None:
    redis = AsyncMock()
    redis.hset = AsyncMock()
    redis.expire = AsyncMock()

    with (
        patch.object(google_calendar.settings, "google_calendar_client_id", "client-id"),
        patch.object(
            google_calendar.settings,
            "google_calendar_client_secret",
            SimpleNamespace(get_secret_value=lambda: "client-secret"),
        ),
        patch.object(google_calendar, "get_redis", AsyncMock(return_value=redis)),
    ):
        url = await google_calendar.create_authorization_url(
            user_id=42,
            return_url=f"{google_calendar.settings.frontend_url}/settings?tab=integrations",
        )

    assert "access_type=offline" in url
    assert "prompt=consent" in url
    assert "calendar.freebusy" in url
    assert "calendar.events.owned" in url
    assert "calendar.calendarlist.readonly" in url
    assert "auth%2Fcalendar+" not in url
    redis.hset.assert_awaited_once()
    redis.expire.assert_awaited_once_with(
        redis.hset.await_args.args[0],
        600,
    )


@pytest.mark.asyncio
async def test_oauth_state_is_consumed_once() -> None:
    pipe = MagicMock()
    pipe.hgetall.return_value = pipe
    pipe.delete.return_value = pipe
    pipe.execute = AsyncMock(
        return_value=[
            {
                "user_id": "12",
                "return_url": f"{google_calendar.settings.frontend_url}/settings",
            },
            1,
        ]
    )
    redis = MagicMock()
    redis.pipeline.return_value = pipe

    with patch.object(google_calendar, "get_redis", AsyncMock(return_value=redis)):
        state = await google_calendar.consume_oauth_state("state-token")

    assert state.user_id == 12
    pipe.delete.assert_called_once_with("google-calendar-oauth:state-token")


@pytest.mark.asyncio
async def test_filter_available_slots_removes_every_overlap() -> None:
    start = datetime(2026, 8, 13, 14, 0, tzinfo=UTC)
    slots = [start, start + timedelta(minutes=30), start + timedelta(minutes=60)]
    db = AsyncMock()

    with patch.object(
        google_calendar,
        "busy_periods",
        AsyncMock(return_value=[(start + timedelta(minutes=15), start + timedelta(minutes=45))]),
    ):
        result = await google_calendar.filter_available_slots(
            db,
            user_id=1,
            slots=slots,
            duration=timedelta(minutes=30),
            timezone="America/New_York",
        )

    assert result == [slots[2]]


@pytest.mark.asyncio
async def test_busy_periods_requires_a_connected_calendar() -> None:
    result = MagicMock()
    result.scalar_one_or_none.return_value = None
    db = AsyncMock()
    db.execute.return_value = result

    with pytest.raises(GoogleCalendarError, match="not connected"):
        await google_calendar.busy_periods(
            db,
            user_id=9,
            starts_at=datetime(2026, 8, 13, 14, 0, tzinfo=UTC),
            ends_at=datetime(2026, 8, 13, 15, 0, tzinfo=UTC),
        )


@pytest.mark.asyncio
async def test_busy_periods_includes_blocks_from_subscribed_calendars() -> None:
    start = datetime(2026, 8, 24, 15, 30, tzinfo=UTC)
    end = start + timedelta(minutes=30)
    connection = SimpleNamespace(
        calendar_id="primary",
        granted_scopes="https://www.googleapis.com/auth/calendar.calendarlist.readonly",
    )
    request = AsyncMock(
        side_effect=[
            {
                "items": [
                    {"id": "owner-calendar", "primary": True},
                    {"id": "field-team"},
                ]
            },
            {
                "calendars": {
                    "owner-calendar": {"busy": []},
                    "field-team": {"busy": [{"start": start.isoformat(), "end": end.isoformat()}]},
                }
            },
        ]
    )

    with (
        patch.object(google_calendar, "get_connection", AsyncMock(return_value=connection)),
        patch.object(google_calendar, "_calendar_request", request),
    ):
        periods = await google_calendar.busy_periods(
            AsyncMock(),
            user_id=1,
            starts_at=start,
            ends_at=end,
        )

    assert periods == [(start, end)]
    assert request.await_args_list[1].kwargs["json"]["items"] == [
        {"id": "owner-calendar"},
        {"id": "field-team"},
    ]


@pytest.mark.asyncio
async def test_busy_periods_ignores_google_calendar_not_found_entries() -> None:
    start = datetime(2026, 8, 24, 15, 30, tzinfo=UTC)
    end = start + timedelta(minutes=30)
    connection = SimpleNamespace(
        calendar_id="primary",
        granted_scopes="https://www.googleapis.com/auth/calendar.calendarlist.readonly",
    )
    request = AsyncMock(
        side_effect=[
            {"items": [{"id": "primary"}, {"id": "holidays"}, {"id": "field-team"}]},
            {
                "calendars": {
                    "primary": {"busy": []},
                    "holidays": {"errors": [{"reason": "notFound"}]},
                    "field-team": {"busy": [{"start": start.isoformat(), "end": end.isoformat()}]},
                }
            },
        ]
    )

    with (
        patch.object(google_calendar, "get_connection", AsyncMock(return_value=connection)),
        patch.object(google_calendar, "_calendar_request", request),
    ):
        periods = await google_calendar.busy_periods(
            AsyncMock(),
            user_id=1,
            starts_at=start,
            ends_at=end,
        )

    assert periods == [(start, end)]


@pytest.mark.asyncio
async def test_busy_periods_fails_closed_when_any_calendar_cannot_be_read() -> None:
    connection = SimpleNamespace(
        calendar_id="primary",
        granted_scopes="https://www.googleapis.com/auth/calendar.calendarlist.readonly",
    )
    request = AsyncMock(
        side_effect=[
            {"items": [{"id": "primary"}, {"id": "field-team"}]},
            {"calendars": {"primary": {"busy": []}}},
        ]
    )

    with (
        patch.object(google_calendar, "get_connection", AsyncMock(return_value=connection)),
        patch.object(google_calendar, "_calendar_request", request),
        pytest.raises(GoogleCalendarError, match="every calendar"),
    ):
        await google_calendar.busy_periods(
            AsyncMock(),
            user_id=1,
            starts_at=datetime(2026, 8, 24, 15, 30, tzinfo=UTC),
            ends_at=datetime(2026, 8, 24, 16, 0, tzinfo=UTC),
        )


@pytest.mark.asyncio
async def test_create_event_uses_deterministic_google_event_id() -> None:
    connection = SimpleNamespace(calendar_id="primary")
    db = AsyncMock()
    request = AsyncMock(
        return_value={
            "id": "tribunalappointment17",
            "htmlLink": "https://calendar.google.com/event?eid=17",
        }
    )
    with (
        patch.object(google_calendar, "get_connection", AsyncMock(return_value=connection)),
        patch.object(google_calendar, "_calendar_request", request),
    ):
        event = await google_calendar.create_event(
            db,
            user_id=1,
            starts_at=datetime(2026, 8, 13, 14, 0, tzinfo=UTC),
            timezone="America/New_York",
            summary="Estimate",
            description=None,
            attendee_email="dana@example.com",
            location=None,
            conference=True,
            event_id="tribunalappointment17",
        )

    assert event.event_id == "tribunalappointment17"
    body = request.await_args.kwargs["json"]
    assert body["id"] == "tribunalappointment17"
    assert body["conferenceData"]["createRequest"]["requestId"] == "tribunalappointment17"
    assert request.await_args.kwargs["params"]["conferenceDataVersion"] == "1"


@pytest.mark.asyncio
async def test_filter_available_slots_rejects_naive_datetimes() -> None:
    with pytest.raises(GoogleCalendarError, match="timezone"):
        await google_calendar.filter_available_slots(
            AsyncMock(),
            user_id=1,
            slots=[datetime(2026, 8, 13, 10, 0)],
            duration=timedelta(minutes=30),
            timezone="America/New_York",
        )
