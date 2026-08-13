"""Google Calendar OAuth, free/busy, and event operations.

The AI never receives Google credentials.  Callers identify the assigned CRM
user; this service loads and refreshes that user's encrypted token server-side.
"""

from __future__ import annotations

import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import urlencode

import httpx
import structlog
from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.db.redis import get_redis
from app.models.google_calendar_connection import GoogleCalendarConnection

logger = structlog.get_logger(__name__)

GOOGLE_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
GOOGLE_REVOKE_URL = "https://oauth2.googleapis.com/revoke"
GOOGLE_USERINFO_URL = "https://openidconnect.googleapis.com/v1/userinfo"
GOOGLE_CALENDAR_API = "https://www.googleapis.com/calendar/v3"
GOOGLE_CALENDAR_SCOPES = (
    "openid",
    "email",
    # Google exposes read-only busy data and owned-event writes as separate least-
    # privilege scopes. Avoid the broader full-calendar scope.
    "https://www.googleapis.com/auth/calendar.events.owned",
    "https://www.googleapis.com/auth/calendar.freebusy",
)
_OAUTH_STATE_PREFIX = "google-calendar-oauth:"
_OAUTH_STATE_TTL_SECONDS = 600
_HTTP_TIMEOUT_SECONDS = 15.0
_REFRESH_SKEW = timedelta(minutes=2)


class GoogleCalendarError(RuntimeError):
    """Safe, expected Google Calendar operation failure."""


@dataclass(frozen=True)
class GoogleOAuthState:
    user_id: int
    return_url: str


@dataclass(frozen=True)
class GoogleEvent:
    event_id: str
    html_link: str | None
    meet_link: str | None


def _oauth_redirect_uri() -> str:
    configured = settings.google_calendar_oauth_redirect_uri.strip()
    if configured:
        return configured
    base_url = settings.public_base_url.rstrip("/")
    return f"{base_url}/api/v1/integrations/google-calendar/callback"


def google_calendar_configured() -> bool:
    """Return whether application-level OAuth credentials are present."""
    return bool(
        settings.google_calendar_client_id.strip()
        and settings.google_calendar_client_secret.get_secret_value().strip()
    )


def _require_configuration() -> None:
    if not google_calendar_configured():
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Google Calendar OAuth is not configured",
        )


def _normalize_return_url(return_url: str | None) -> str:
    """Keep OAuth redirects on the configured frontend origin."""
    default = f"{settings.frontend_url.rstrip('/')}/settings?tab=calendar"
    if not return_url:
        return default
    frontend = settings.frontend_url.rstrip("/")
    if return_url == frontend or return_url.startswith(f"{frontend}/"):
        return return_url
    return default


async def create_authorization_url(*, user_id: int, return_url: str | None = None) -> str:
    """Create a one-time OAuth URL bound to the signed-in user."""
    _require_configuration()
    state = secrets.token_urlsafe(32)
    redis = await get_redis()
    await redis.hset(  # type: ignore[misc]
        _OAUTH_STATE_PREFIX + state,
        mapping={
            "user_id": str(user_id),
            "return_url": _normalize_return_url(return_url),
        },
    )
    await redis.expire(_OAUTH_STATE_PREFIX + state, _OAUTH_STATE_TTL_SECONDS)

    params = {
        "client_id": settings.google_calendar_client_id,
        "redirect_uri": _oauth_redirect_uri(),
        "response_type": "code",
        "scope": " ".join(GOOGLE_CALENDAR_SCOPES),
        "access_type": "offline",
        "include_granted_scopes": "true",
        "prompt": "consent",
        "state": state,
    }
    return f"{GOOGLE_AUTH_URL}?{urlencode(params)}"


async def consume_oauth_state(state: str) -> GoogleOAuthState:
    """Atomically consume OAuth state to prevent replay and login confusion."""
    redis = await get_redis()
    key = _OAUTH_STATE_PREFIX + state
    pipe = redis.pipeline(transaction=True)
    pipe.hgetall(key)
    pipe.delete(key)
    result = await pipe.execute()
    values = result[0]
    if not values or "user_id" not in values:
        raise GoogleCalendarError("Google authorization expired or was already used")
    return GoogleOAuthState(
        user_id=int(values["user_id"]),
        return_url=_normalize_return_url(values.get("return_url")),
    )


async def _post_form(url: str, data: dict[str, str]) -> dict[str, Any]:
    async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT_SECONDS) as client:
        response = await client.post(url, data=data)
    try:
        payload = response.json()
    except ValueError as exc:
        raise GoogleCalendarError("Google returned an invalid response") from exc
    if response.is_error:
        description = payload.get("error_description") or payload.get("error")
        logger.warning(
            "google_calendar_http_error",
            endpoint=url,
            status_code=response.status_code,
            error=description,
        )
        raise GoogleCalendarError("Google Calendar authorization failed")
    if not isinstance(payload, dict):
        raise GoogleCalendarError("Google returned an invalid response")
    return payload


async def exchange_code_and_save(
    db: AsyncSession,
    *,
    user_id: int,
    code: str,
) -> GoogleCalendarConnection:
    """Exchange an OAuth code and upsert the user's encrypted connection."""
    _require_configuration()
    token_payload = await _post_form(
        GOOGLE_TOKEN_URL,
        {
            "client_id": settings.google_calendar_client_id,
            "client_secret": settings.google_calendar_client_secret.get_secret_value(),
            "code": code,
            "grant_type": "authorization_code",
            "redirect_uri": _oauth_redirect_uri(),
        },
    )
    access_token = str(token_payload.get("access_token") or "")
    if not access_token:
        raise GoogleCalendarError("Google did not return an access token")

    async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT_SECONDS) as client:
        user_response = await client.get(
            GOOGLE_USERINFO_URL,
            headers={"Authorization": f"Bearer {access_token}"},
        )
    if user_response.is_error:
        raise GoogleCalendarError("Could not read the authorized Google account")
    user_info = user_response.json()
    google_account_id = str(user_info.get("sub") or "")
    google_email = str(user_info.get("email") or "")
    if not google_account_id or not google_email:
        raise GoogleCalendarError("Google account identity was incomplete")

    result = await db.execute(
        select(GoogleCalendarConnection).where(GoogleCalendarConnection.user_id == user_id)
    )
    connection = result.scalar_one_or_none()
    returned_refresh_token = str(token_payload.get("refresh_token") or "")
    if connection is None and not returned_refresh_token:
        raise GoogleCalendarError("Google did not grant offline calendar access")

    expires_in = int(token_payload.get("expires_in") or 3600)
    expires_at = datetime.now(UTC) + timedelta(seconds=max(0, expires_in))
    scopes = str(token_payload.get("scope") or " ".join(GOOGLE_CALENDAR_SCOPES))

    if connection is None:
        connection = GoogleCalendarConnection(
            user_id=user_id,
            google_account_id=google_account_id,
            google_email=google_email,
            access_token=access_token,
            refresh_token=returned_refresh_token,
            access_token_expires_at=expires_at,
            granted_scopes=scopes,
        )
        db.add(connection)
    else:
        connection.google_account_id = google_account_id
        connection.google_email = google_email
        connection.access_token = access_token
        if returned_refresh_token:
            connection.refresh_token = returned_refresh_token
        connection.access_token_expires_at = expires_at
        connection.granted_scopes = scopes

    await db.commit()
    await db.refresh(connection)
    return connection


async def get_connection(
    db: AsyncSession,
    user_id: int,
) -> GoogleCalendarConnection | None:
    result = await db.execute(
        select(GoogleCalendarConnection).where(GoogleCalendarConnection.user_id == user_id)
    )
    return result.scalar_one_or_none()


async def _access_token(db: AsyncSession, connection: GoogleCalendarConnection) -> str:
    now = datetime.now(UTC)
    expires_at = connection.access_token_expires_at
    if connection.access_token and expires_at and expires_at > now + _REFRESH_SKEW:
        return connection.access_token

    payload = await _post_form(
        GOOGLE_TOKEN_URL,
        {
            "client_id": settings.google_calendar_client_id,
            "client_secret": settings.google_calendar_client_secret.get_secret_value(),
            "refresh_token": connection.refresh_token,
            "grant_type": "refresh_token",
        },
    )
    access_token = str(payload.get("access_token") or "")
    if not access_token:
        raise GoogleCalendarError("Google Calendar access needs to be reconnected")
    connection.access_token = access_token
    connection.access_token_expires_at = now + timedelta(
        seconds=max(0, int(payload.get("expires_in") or 3600))
    )
    await db.commit()
    return access_token


async def _calendar_request(
    db: AsyncSession,
    connection: GoogleCalendarConnection,
    method: str,
    path: str,
    *,
    json: dict[str, Any] | None = None,
    params: dict[str, str] | None = None,
) -> dict[str, Any]:
    token = await _access_token(db, connection)
    async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT_SECONDS) as client:
        response = await client.request(
            method,
            GOOGLE_CALENDAR_API + path,
            headers={"Authorization": f"Bearer {token}"},
            json=json,
            params=params,
        )
    if response.is_error:
        logger.warning(
            "google_calendar_api_error",
            method=method,
            path=path,
            status_code=response.status_code,
        )
        if response.status_code in {401, 403}:
            raise GoogleCalendarError("Google Calendar access needs to be reconnected")
        if response.status_code == 404:
            raise GoogleCalendarError("Google Calendar event was not found")
        if response.status_code == 409:
            raise GoogleCalendarError("That time is no longer available")
        raise GoogleCalendarError("Google Calendar is temporarily unavailable")
    if response.status_code == 204 or not response.content:
        return {}
    payload = response.json()
    if not isinstance(payload, dict):
        raise GoogleCalendarError("Google returned an invalid calendar response")
    return payload


async def busy_periods(
    db: AsyncSession,
    *,
    user_id: int,
    starts_at: datetime,
    ends_at: datetime,
) -> list[tuple[datetime, datetime]]:
    """Return the connected user's Google busy intervals in UTC."""
    connection = await get_connection(db, user_id)
    if connection is None:
        raise GoogleCalendarError("The assigned team member has not connected Google Calendar")
    payload = await _calendar_request(
        db,
        connection,
        "POST",
        "/freeBusy",
        json={
            "timeMin": starts_at.astimezone(UTC).isoformat(),
            "timeMax": ends_at.astimezone(UTC).isoformat(),
            "items": [{"id": connection.calendar_id}],
        },
    )
    calendar = (payload.get("calendars") or {}).get(connection.calendar_id) or {}
    if calendar.get("errors"):
        raise GoogleCalendarError("Google could not read this calendar's availability")
    periods: list[tuple[datetime, datetime]] = []
    for item in calendar.get("busy") or []:
        try:
            periods.append(
                (
                    datetime.fromisoformat(str(item["start"]).replace("Z", "+00:00")),
                    datetime.fromisoformat(str(item["end"]).replace("Z", "+00:00")),
                )
            )
        except (KeyError, TypeError, ValueError):
            continue
    return periods


async def is_time_available(
    db: AsyncSession,
    *,
    user_id: int,
    starts_at: datetime,
    ends_at: datetime,
) -> bool:
    return not await busy_periods(
        db,
        user_id=user_id,
        starts_at=starts_at,
        ends_at=ends_at,
    )


async def create_event(
    db: AsyncSession,
    *,
    user_id: int,
    starts_at: datetime,
    timezone: str,
    summary: str,
    description: str | None,
    attendee_email: str | None,
    location: str | None,
    ends_at: datetime | None = None,
    duration_minutes: int = 30,
    attendee_name: str | None = None,
    conference: bool = False,
    event_id: str | None = None,
) -> GoogleEvent:
    """Insert one confirmed CRM appointment into its assigned user's calendar."""
    connection = await get_connection(db, user_id)
    if connection is None:
        raise GoogleCalendarError("The assigned team member has not connected Google Calendar")
    if starts_at.tzinfo is None:
        raise GoogleCalendarError("Calendar event time must include a timezone")
    event_ends_at = ends_at or (starts_at + timedelta(minutes=duration_minutes))
    body: dict[str, Any] = {
        "summary": summary,
        "description": description or "",
        "start": {"dateTime": starts_at.isoformat(), "timeZone": timezone},
        "end": {"dateTime": event_ends_at.isoformat(), "timeZone": timezone},
        "extendedProperties": {"private": {"source": "the-tribunal"}},
    }
    if event_id:
        body["id"] = event_id
    if attendee_email:
        attendee: dict[str, str] = {"email": attendee_email}
        if attendee_name:
            attendee["displayName"] = attendee_name
        body["attendees"] = [attendee]
    if location:
        body["location"] = location
    params = {"sendUpdates": "all" if attendee_email else "none"}
    stable_request_id = event_id or secrets.token_hex(16)
    if conference:
        body["conferenceData"] = {
            "createRequest": {
                "requestId": stable_request_id,
                "conferenceSolutionKey": {"type": "hangoutsMeet"},
            }
        }
        params["conferenceDataVersion"] = "1"
    from urllib.parse import quote

    try:
        payload = await _calendar_request(
            db,
            connection,
            "POST",
            f"/calendars/{quote(connection.calendar_id, safe='')}/events",
            json=body,
            params=params,
        )
    except GoogleCalendarError as exc:
        if not event_id or "no longer available" not in str(exc):
            raise
        # A retried finalizer can race after Google accepted the first insert but
        # before the CRM stored its response. The deterministic id makes that
        # retry resolve the original event instead of sending a duplicate invite.
        payload = await _calendar_request(
            db,
            connection,
            "GET",
            (
                f"/calendars/{quote(connection.calendar_id, safe='')}"
                f"/events/{quote(event_id, safe='')}"
            ),
        )
    event_id = str(payload.get("id") or "")
    if not event_id:
        raise GoogleCalendarError("Google created an incomplete calendar event")
    return GoogleEvent(
        event_id=event_id,
        html_link=str(payload.get("htmlLink")) if payload.get("htmlLink") else None,
        meet_link=str(payload.get("hangoutLink")) if payload.get("hangoutLink") else None,
    )


async def filter_available_slots(
    db: AsyncSession,
    *,
    user_id: int,
    slots: list[datetime],
    duration: timedelta,
    timezone: str,
) -> list[datetime]:
    """Return candidate slots that do not overlap the user's Google busy time."""
    del timezone  # Datetimes carry their offsets; retained for an explicit API contract.
    if not slots:
        return []
    if any(slot.tzinfo is None for slot in slots):
        raise GoogleCalendarError("Availability slots must include a timezone")
    periods = await busy_periods(
        db,
        user_id=user_id,
        starts_at=min(slots),
        ends_at=max(slots) + duration,
    )
    return [
        slot
        for slot in slots
        if all(
            slot + duration <= busy_start or slot >= busy_end for busy_start, busy_end in periods
        )
    ]


async def update_event_time(
    db: AsyncSession,
    *,
    user_id: int,
    event_id: str,
    starts_at: datetime,
    duration_minutes: int,
    timezone: str,
) -> None:
    """Move an existing event on its owning user's Google Calendar."""
    connection = await get_connection(db, user_id)
    if connection is None:
        raise GoogleCalendarError("The assigned team member has not connected Google Calendar")
    if starts_at.tzinfo is None:
        raise GoogleCalendarError("Calendar event time must include a timezone")
    from urllib.parse import quote

    await _calendar_request(
        db,
        connection,
        "PATCH",
        f"/calendars/{quote(connection.calendar_id, safe='')}/events/{quote(event_id, safe='')}",
        json={
            "start": {"dateTime": starts_at.isoformat(), "timeZone": timezone},
            "end": {
                "dateTime": (starts_at + timedelta(minutes=duration_minutes)).isoformat(),
                "timeZone": timezone,
            },
        },
        params={"sendUpdates": "all"},
    )


async def delete_event(db: AsyncSession, *, user_id: int, event_id: str) -> None:
    connection = await get_connection(db, user_id)
    if connection is None:
        return
    from urllib.parse import quote

    await _calendar_request(
        db,
        connection,
        "DELETE",
        f"/calendars/{quote(connection.calendar_id, safe='')}/events/{quote(event_id, safe='')}",
        params={"sendUpdates": "all"},
    )


async def disconnect(db: AsyncSession, *, user_id: int) -> None:
    """Revoke Google access best-effort, then delete the local credentials."""
    connection = await get_connection(db, user_id)
    if connection is None:
        return
    token = connection.refresh_token
    try:
        async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT_SECONDS) as client:
            await client.post(GOOGLE_REVOKE_URL, data={"token": token})
    except httpx.HTTPError as exc:
        logger.warning("google_calendar_revoke_failed", user_id=user_id, error=str(exc))
    await db.delete(connection)
    await db.commit()
