"""Unit tests for scoped Zoom meeting creation and URL handling."""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, patch

import httpx
import pytest

from app.services import zoom
from app.services.zoom import ZoomError
from app.utils.meeting_urls import meeting_provider_name, zoom_meeting_id_from_url


def _zoom_settings() -> tuple[Any, ...]:
    return (
        patch.object(zoom.settings, "zoom_account_id", "account-id"),
        patch.object(zoom.settings, "zoom_client_id", "client-id"),
        patch.object(
            zoom.settings,
            "zoom_client_secret",
            SimpleNamespace(get_secret_value=lambda: "client-secret"),
        ),
        patch.object(zoom.settings, "zoom_host_email", "max@maxteriors.com"),
    )


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("https://us06web.zoom.us/j/12345678901?pwd=opaque", "12345678901"),
        ("https://zoom.us/j/123456789", "123456789"),
        ("http://zoom.us/j/123456789", None),
        ("https://zoom.us.evil.example/j/123456789", None),
        ("https://user@zoom.us/j/123456789", None),
        ("https://zoom.us/wc/join/123456789", None),
        ("https://meet.google.com/abc-defg-hij", None),
        (None, None),
    ],
)
def test_zoom_meeting_id_requires_canonical_https_join_url(
    value: str | None,
    expected: str | None,
) -> None:
    assert zoom_meeting_id_from_url(value) == expected


def test_meeting_provider_name_is_customer_safe() -> None:
    assert meeting_provider_name("https://us06web.zoom.us/j/12345678901?pwd=opaque") == "Zoom"
    assert meeting_provider_name("https://MEET.GOOGLE.COM/abc-defg-hij") == "Google Meet"
    assert meeting_provider_name("https://user@meet.google.com/abc-defg-hij") == "video meeting"
    assert meeting_provider_name("https://video.example.com/room") == "video meeting"


@pytest.mark.asyncio
async def test_create_meeting_uses_private_waiting_room_defaults() -> None:
    request = AsyncMock(
        return_value={
            "id": 12345678901,
            "join_url": "https://us06web.zoom.us/j/12345678901?pwd=opaque",
            "start_url": "https://zoom.us/s/host-secret",
        }
    )
    contexts = _zoom_settings()
    with (
        contexts[0],
        contexts[1],
        contexts[2],
        contexts[3],
        patch.object(zoom, "_request", request),
    ):
        meeting = await zoom.create_meeting(
            starts_at=datetime(2026, 8, 20, 14, 0, tzinfo=UTC),
            duration_minutes=30,
            timezone="America/New_York",
            topic="Maxteriors consultation",
            agenda="Appointment 42",
        )

    assert meeting.meeting_id == "12345678901"
    assert meeting.join_url.endswith("?pwd=opaque")
    call = request.await_args
    assert call.args == (
        "POST",
        "/users/max%40maxteriors.com/meetings",
    )
    body = call.kwargs["json"]
    assert body["start_time"] == "2026-08-20T14:00:00Z"
    assert body["settings"]["waiting_room"] is True
    assert body["settings"]["join_before_host"] is False
    assert body["settings"]["auto_recording"] == "none"
    assert body["settings"]["meeting_authentication"] is False
    assert "start_url" not in body


@pytest.mark.asyncio
async def test_create_meeting_rejects_untrusted_join_url() -> None:
    contexts = _zoom_settings()
    with (
        contexts[0],
        contexts[1],
        contexts[2],
        contexts[3],
        patch.object(
            zoom,
            "_request",
            AsyncMock(
                return_value={
                    "id": 12345678901,
                    "join_url": "https://zoom.us.evil.example/j/12345678901",
                }
            ),
        ),
        pytest.raises(ZoomError, match="invalid meeting response"),
    ):
        await zoom.create_meeting(
            starts_at=datetime(2026, 8, 20, 14, 0, tzinfo=UTC),
            duration_minutes=30,
            timezone="America/New_York",
            topic="Maxteriors consultation",
        )


@pytest.mark.asyncio
async def test_create_meeting_rejects_passcode_not_embedded_in_join_url() -> None:
    contexts = _zoom_settings()
    with (
        contexts[0],
        contexts[1],
        contexts[2],
        contexts[3],
        patch.object(
            zoom,
            "_request",
            AsyncMock(
                return_value={
                    "id": 12345678901,
                    "join_url": "https://us06web.zoom.us/j/12345678901",
                    "password": "separate-passcode",
                }
            ),
        ),
        pytest.raises(ZoomError, match="invalid meeting response"),
    ):
        await zoom.create_meeting(
            starts_at=datetime(2026, 8, 20, 14, 0, tzinfo=UTC),
            duration_minutes=30,
            timezone="America/New_York",
            topic="Maxteriors consultation",
        )


@pytest.mark.asyncio
async def test_update_and_delete_use_only_validated_meeting_id() -> None:
    request = AsyncMock(return_value={})
    contexts = _zoom_settings()
    with (
        contexts[0],
        contexts[1],
        contexts[2],
        contexts[3],
        patch.object(zoom, "_request", request),
    ):
        await zoom.update_meeting(
            meeting_id="12345678901",
            starts_at=datetime(2026, 8, 20, 15, 0, tzinfo=UTC),
            duration_minutes=45,
            timezone="America/New_York",
        )
        await zoom.delete_meeting(meeting_id="12345678901")

    assert request.await_args_list[0].args == ("PATCH", "/meetings/12345678901")
    assert request.await_args_list[1].args == ("DELETE", "/meetings/12345678901")
    assert request.await_args_list[1].kwargs["missing_is_success"] is True


@pytest.mark.asyncio
async def test_zoom_is_scoped_to_matching_google_calendar_owner() -> None:
    matching_result = SimpleNamespace(scalar_one_or_none=lambda: "max@maxteriors.com")
    other_result = SimpleNamespace(scalar_one_or_none=lambda: "other@example.com")
    db = AsyncMock()
    contexts = _zoom_settings()
    with contexts[0], contexts[1], contexts[2], contexts[3]:
        db.execute.return_value = matching_result
        assert await zoom.zoom_configured_for_user(db, user_id=42) is True
        db.execute.return_value = other_result
        assert await zoom.zoom_configured_for_user(db, user_id=42) is False


@pytest.mark.asyncio
async def test_full_http_flow_uses_server_credentials_without_returning_host_url() -> None:
    real_async_client = httpx.AsyncClient

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "zoom.us":
            assert request.url.params["grant_type"] == "account_credentials"
            assert request.url.params["account_id"] == "account-id"
            assert request.headers["Authorization"].startswith("Basic ")
            return httpx.Response(
                200,
                json={"access_token": "provider-access-token", "expires_in": 3600},
            )
        assert request.url.path == "/v2/users/max@maxteriors.com/meetings"
        assert request.headers["Authorization"] == "Bearer provider-access-token"
        return httpx.Response(
            201,
            json={
                "id": 12345678901,
                "join_url": "https://us06web.zoom.us/j/12345678901?pwd=opaque",
                "start_url": "https://zoom.us/s/host-secret",
            },
        )

    transport = httpx.MockTransport(handler)
    contexts = _zoom_settings()
    zoom._access_token_cache.token = None
    zoom._access_token_cache.expires_at = datetime.min.replace(tzinfo=UTC)
    with (
        contexts[0],
        contexts[1],
        contexts[2],
        contexts[3],
        patch.object(
            zoom.httpx,
            "AsyncClient",
            side_effect=lambda **kwargs: real_async_client(transport=transport, **kwargs),
        ),
    ):
        meeting = await zoom.create_meeting(
            starts_at=datetime(2026, 8, 20, 14, 0, tzinfo=UTC),
            duration_minutes=30,
            timezone="America/New_York",
            topic="Maxteriors consultation",
        )

    assert meeting.join_url.endswith("?pwd=opaque")
    assert "host-secret" not in meeting.join_url


@pytest.mark.asyncio
async def test_zoom_authorization_error_does_not_expose_provider_message() -> None:
    real_async_client = httpx.AsyncClient

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            401,
            json={"code": 124, "message": "bad do-not-leak-client-secret"},
        )

    transport = httpx.MockTransport(handler)
    contexts = _zoom_settings()
    zoom._access_token_cache.token = None
    zoom._access_token_cache.expires_at = datetime.min.replace(tzinfo=UTC)
    with (
        contexts[0],
        contexts[1],
        contexts[2],
        contexts[3],
        patch.object(
            zoom.httpx,
            "AsyncClient",
            side_effect=lambda **kwargs: real_async_client(transport=transport, **kwargs),
        ),
        pytest.raises(ZoomError) as exc_info,
    ):
        await zoom.create_meeting(
            starts_at=datetime(2026, 8, 20, 14, 0, tzinfo=UTC),
            duration_minutes=30,
            timezone="America/New_York",
            topic="Maxteriors consultation",
        )

    assert str(exc_info.value) == "Zoom authorization failed"
    assert "do-not-leak-client-secret" not in str(exc_info.value)
