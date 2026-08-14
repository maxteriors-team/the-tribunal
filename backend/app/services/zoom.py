"""Server-side Zoom meeting operations for one configured calendar owner.

Zoom credentials and access tokens never leave the backend. The configured host
email must match the assigned representative's connected Google account, which
prevents one workspace from creating meetings on another tenant's Zoom account.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import parse_qs, quote, urlsplit

import httpx
import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.google_calendar_connection import GoogleCalendarConnection
from app.utils.meeting_urls import zoom_meeting_id_from_url

logger = structlog.get_logger(__name__)

ZOOM_TOKEN_URL = "https://zoom.us/oauth/token"
ZOOM_API_BASE_URL = "https://api.zoom.us/v2"
_HTTP_TIMEOUT_SECONDS = 15.0
_TOKEN_REFRESH_SKEW = timedelta(minutes=2)


@dataclass
class _AccessTokenCache:
    token: str | None = None
    expires_at: datetime = datetime.min.replace(tzinfo=UTC)


_access_token_cache = _AccessTokenCache()
_token_lock = asyncio.Lock()


class ZoomError(RuntimeError):
    """Safe, expected Zoom operation failure."""


@dataclass(frozen=True)
class ZoomMeeting:
    meeting_id: str
    join_url: str


def zoom_configured() -> bool:
    """Return whether the complete server-to-server OAuth configuration exists."""
    return settings.zoom_enabled


async def zoom_configured_for_user(db: AsyncSession, *, user_id: int) -> bool:
    """Restrict Zoom creation to the matching Google-connected calendar owner."""
    if not zoom_configured():
        return False
    result = await db.execute(
        select(GoogleCalendarConnection.google_email).where(
            GoogleCalendarConnection.user_id == user_id
        )
    )
    google_email = result.scalar_one_or_none()
    return bool(
        google_email and google_email.casefold() == settings.zoom_host_email.strip().casefold()
    )


async def create_meeting(
    *,
    starts_at: datetime,
    duration_minutes: int,
    timezone: str,
    topic: str,
    agenda: str | None = None,
) -> ZoomMeeting:
    """Create a unique, waiting-room-protected Zoom meeting."""
    _require_configuration()
    if starts_at.tzinfo is None:
        raise ZoomError("Zoom meeting start time must include a timezone")

    payload = await _request(
        "POST",
        f"/users/{quote(settings.zoom_host_email.strip(), safe='')}/meetings",
        operation="create_meeting",
        json={
            "topic": topic[:200],
            "type": 2,
            "start_time": starts_at.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "duration": duration_minutes,
            "timezone": timezone,
            "agenda": (agenda or "")[:2000],
            "settings": {
                "approval_type": 2,
                "audio": "both",
                "auto_recording": "none",
                "host_video": True,
                "join_before_host": False,
                "meeting_authentication": False,
                "mute_upon_entry": True,
                "participant_video": False,
                "waiting_room": True,
            },
        },
    )
    meeting_id = str(payload.get("id") or "")
    join_url = str(payload.get("join_url") or "")
    parsed_meeting_id = zoom_meeting_id_from_url(join_url)
    join_query = parse_qs(urlsplit(join_url).query) if parsed_meeting_id else {}
    passcode_requires_separate_delivery = bool(payload.get("password")) and not join_query.get(
        "pwd"
    )
    if not meeting_id or parsed_meeting_id != meeting_id or passcode_requires_separate_delivery:
        raise ZoomError("Zoom returned an invalid meeting response")
    return ZoomMeeting(meeting_id=meeting_id, join_url=join_url)


async def update_meeting(
    *,
    meeting_id: str,
    starts_at: datetime,
    duration_minutes: int,
    timezone: str,
) -> None:
    """Update a scheduled Zoom meeting without changing its customer join URL."""
    _require_configuration()
    if starts_at.tzinfo is None:
        raise ZoomError("Zoom meeting start time must include a timezone")
    await _request(
        "PATCH",
        f"/meetings/{quote(meeting_id, safe='')}",
        operation="update_meeting",
        json={
            "start_time": starts_at.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "duration": duration_minutes,
            "timezone": timezone,
        },
    )


async def delete_meeting(*, meeting_id: str) -> None:
    """Delete a Zoom meeting; an already-missing meeting is success."""
    _require_configuration()
    await _request(
        "DELETE",
        f"/meetings/{quote(meeting_id, safe='')}",
        operation="delete_meeting",
        missing_is_success=True,
    )


def _require_configuration() -> None:
    if not zoom_configured():
        raise ZoomError("Zoom is not configured")


async def _access_token(*, force_refresh: bool = False) -> str:
    now = datetime.now(UTC)
    if (
        not force_refresh
        and _access_token_cache.token
        and _access_token_cache.expires_at > now + _TOKEN_REFRESH_SKEW
    ):
        return _access_token_cache.token

    async with _token_lock:
        now = datetime.now(UTC)
        if (
            not force_refresh
            and _access_token_cache.token
            and _access_token_cache.expires_at > now + _TOKEN_REFRESH_SKEW
        ):
            return _access_token_cache.token

        async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT_SECONDS) as client:
            response = await client.post(
                ZOOM_TOKEN_URL,
                params={
                    "grant_type": "account_credentials",
                    "account_id": settings.zoom_account_id.strip(),
                },
                auth=(
                    settings.zoom_client_id.strip(),
                    settings.zoom_client_secret.get_secret_value(),
                ),
                headers={"Accept": "application/json"},
            )
        payload = _response_payload(response)
        if response.is_error:
            _log_provider_error("access_token", response, payload)
            raise ZoomError("Zoom authorization failed")

        access_token = str(payload.get("access_token") or "")
        if not access_token:
            raise ZoomError("Zoom returned an invalid authorization response")
        expires_in = max(0, int(payload.get("expires_in") or 3600))
        _access_token_cache.token = access_token
        _access_token_cache.expires_at = now + timedelta(seconds=expires_in)
        return access_token


async def _request(
    method: str,
    path: str,
    *,
    operation: str,
    json: dict[str, Any] | None = None,
    missing_is_success: bool = False,
) -> dict[str, Any]:
    for attempt in range(2):
        token = await _access_token(force_refresh=attempt > 0)
        async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT_SECONDS) as client:
            response = await client.request(
                method,
                f"{ZOOM_API_BASE_URL}{path}",
                headers={
                    "Accept": "application/json",
                    "Authorization": f"Bearer {token}",
                    "Content-Type": "application/json",
                },
                json=json,
            )
        if response.status_code == 401 and attempt == 0:
            continue
        if missing_is_success and response.status_code == 404:
            return {}
        payload = _response_payload(response)
        if response.is_error:
            _log_provider_error(operation, response, payload)
            raise ZoomError(f"Zoom {operation.replace('_', ' ')} failed")
        return payload
    raise ZoomError("Zoom authorization failed")


def _response_payload(response: httpx.Response) -> dict[str, Any]:
    if response.status_code == 204 or not response.content:
        return {}
    try:
        payload = response.json()
    except ValueError as exc:
        raise ZoomError("Zoom returned an invalid response") from exc
    if not isinstance(payload, dict):
        raise ZoomError("Zoom returned an invalid response")
    return payload


def _log_provider_error(
    operation: str,
    response: httpx.Response,
    payload: dict[str, Any],
) -> None:
    logger.warning(
        "zoom_http_error",
        operation=operation,
        status_code=response.status_code,
        provider_code=payload.get("code"),
    )
