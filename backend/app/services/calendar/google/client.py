"""Thin async Google Calendar API v3 client (events + free/busy).

Scoped to exactly what the booking migration needs:
- ``insert_event`` (with a Google Meet link) / ``patch_event`` / ``delete_event``
- ``freebusy`` for the availability engine
- ``list_events`` (incremental sync) + ``watch_events`` / ``stop_channel`` (push)

Auth is a ``token_provider`` coroutine that returns a *fresh* access token
(see :func:`app.services.calendar.google.oauth.ensure_fresh_access_token`), so a
token expiring mid-session is refreshed transparently. Tokens are never logged.
"""

from __future__ import annotations

import uuid
from collections.abc import Awaitable, Callable
from typing import Any, cast

import httpx
import structlog

logger = structlog.get_logger()

GOOGLE_CALENDAR_BASE_URL = "https://www.googleapis.com/calendar/v3"
MEET_CONFERENCE_TYPE = "hangoutsMeet"

TokenProvider = Callable[[], Awaitable[str]]


class GoogleCalendarError(Exception):
    """Base error for Google Calendar API calls."""


class GoogleCalendarAuthError(GoogleCalendarError):
    """Authentication/authorization failure (401/403)."""


class GoogleCalendarNotFoundError(GoogleCalendarError):
    """Referenced calendar/event does not exist (404)."""


class GoogleCalendarSyncTokenError(GoogleCalendarError):
    """The incremental ``syncToken`` is no longer valid (410) — re-baseline."""


class GoogleCalendarClient:
    """Minimal Google Calendar API v3 client for one workspace calendar."""

    def __init__(
        self,
        token_provider: TokenProvider,
        calendar_id: str = "primary",
        *,
        http_client: httpx.AsyncClient | None = None,
        timeout: float = 20.0,
    ) -> None:
        self._token_provider = token_provider
        self._calendar_id = calendar_id
        self._client = http_client
        self._owns_client = http_client is None
        self._timeout = timeout
        self._log = logger.bind(component="google_calendar_client")

    # ── lifecycle ───────────────────────────────────────────────────

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(
                base_url=GOOGLE_CALENDAR_BASE_URL, timeout=self._timeout
            )
        return self._client

    async def close(self) -> None:
        if self._owns_client and self._client is not None:
            await self._client.aclose()
            self._client = None

    # ── low-level request ───────────────────────────────────────────

    async def _request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        token = await self._token_provider()
        client = await self._get_client()
        try:
            response = await client.request(
                method,
                path,
                params=params,
                json=json,
                headers={"Authorization": f"Bearer {token}"},
            )
        except httpx.HTTPError as exc:
            raise GoogleCalendarError(f"Google Calendar request failed: {exc}") from exc

        if response.status_code in (httpx.codes.UNAUTHORIZED, httpx.codes.FORBIDDEN):
            raise GoogleCalendarAuthError(
                f"Google Calendar auth failed (status {response.status_code})"
            )
        if response.status_code == httpx.codes.NOT_FOUND:
            raise GoogleCalendarNotFoundError("Google Calendar resource not found")
        if response.status_code == httpx.codes.GONE:
            raise GoogleCalendarSyncTokenError("Google Calendar sync token expired")
        if response.status_code >= httpx.codes.BAD_REQUEST:
            self._log.warning("google_calendar_api_error", status_code=response.status_code)
            raise GoogleCalendarError(f"Google Calendar API error (status {response.status_code})")
        if response.status_code == httpx.codes.NO_CONTENT or not response.content:
            return {}
        return cast(dict[str, Any], response.json())

    # ── events ──────────────────────────────────────────────────────

    async def insert_event(
        self,
        *,
        summary: str,
        start_iso: str,
        end_iso: str,
        timezone: str,
        attendee_email: str,
        attendee_name: str | None = None,
        description: str | None = None,
        add_meet: bool = True,
        private_properties: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        """Create an event (with a Meet link) and invite the attendee."""
        attendee: dict[str, Any] = {"email": attendee_email}
        if attendee_name:
            attendee["displayName"] = attendee_name

        body: dict[str, Any] = {
            "summary": summary,
            "start": {"dateTime": start_iso, "timeZone": timezone},
            "end": {"dateTime": end_iso, "timeZone": timezone},
            "attendees": [attendee],
        }
        if description:
            body["description"] = description
        if private_properties:
            body["extendedProperties"] = {"private": private_properties}

        params: dict[str, Any] = {"sendUpdates": "all"}
        if add_meet:
            body["conferenceData"] = {
                "createRequest": {
                    "requestId": uuid.uuid4().hex,
                    "conferenceSolutionKey": {"type": MEET_CONFERENCE_TYPE},
                }
            }
            params["conferenceDataVersion"] = 1

        return await self._request(
            "POST",
            f"/calendars/{self._calendar_id}/events",
            params=params,
            json=body,
        )

    async def patch_event(
        self,
        event_id: str,
        *,
        start_iso: str | None = None,
        end_iso: str | None = None,
        timezone: str | None = None,
        summary: str | None = None,
        description: str | None = None,
    ) -> dict[str, Any]:
        """Partially update an event (used for reschedule)."""
        body: dict[str, Any] = {}
        if start_iso is not None:
            body["start"] = {"dateTime": start_iso, "timeZone": timezone}
        if end_iso is not None:
            body["end"] = {"dateTime": end_iso, "timeZone": timezone}
        if summary is not None:
            body["summary"] = summary
        if description is not None:
            body["description"] = description

        return await self._request(
            "PATCH",
            f"/calendars/{self._calendar_id}/events/{event_id}",
            params={"sendUpdates": "all"},
            json=body,
        )

    async def delete_event(self, event_id: str) -> None:
        """Delete (cancel) an event and notify the attendee."""
        try:
            await self._request(
                "DELETE",
                f"/calendars/{self._calendar_id}/events/{event_id}",
                params={"sendUpdates": "all"},
            )
        except GoogleCalendarNotFoundError:
            # Already gone — treat as success (idempotent cancel).
            self._log.info("google_calendar_delete_already_gone", event_id=event_id)

    async def get_event(self, event_id: str) -> dict[str, Any]:
        """Fetch a single event."""
        return await self._request(
            "GET",
            f"/calendars/{self._calendar_id}/events/{event_id}",
        )

    # ── free/busy ───────────────────────────────────────────────────

    async def freebusy(
        self,
        *,
        time_min_iso: str,
        time_max_iso: str,
        timezone: str = "UTC",
        calendar_ids: list[str] | None = None,
    ) -> list[dict[str, str]]:
        """Query busy blocks for the calendar(s) between two instants.

        Returns a flat list of ``{"start", "end"}`` busy intervals (RFC 3339)
        merged across the requested calendars.
        """
        items = [{"id": cid} for cid in (calendar_ids or [self._calendar_id])]
        response = await self._request(
            "POST",
            "/freeBusy",
            json={
                "timeMin": time_min_iso,
                "timeMax": time_max_iso,
                "timeZone": timezone,
                "items": items,
            },
        )
        calendars = response.get("calendars", {})
        busy: list[dict[str, str]] = []
        if isinstance(calendars, dict):
            for cal in calendars.values():
                if isinstance(cal, dict):
                    for block in cal.get("busy", []) or []:
                        if isinstance(block, dict) and "start" in block and "end" in block:
                            busy.append({"start": block["start"], "end": block["end"]})
        return busy

    # ── sync + push channels ────────────────────────────────────────

    async def list_events(
        self,
        *,
        sync_token: str | None = None,
        time_min_iso: str | None = None,
        time_max_iso: str | None = None,
        page_token: str | None = None,
        max_results: int = 250,
    ) -> dict[str, Any]:
        """List events for incremental sync.

        Pass ``sync_token`` for incremental changes; on the first (baseline)
        sync pass ``time_min_iso`` instead. Raises
        :class:`GoogleCalendarSyncTokenError` when the token has expired (410).
        """
        params: dict[str, Any] = {
            "singleEvents": "true",
            "showDeleted": "true",
            "maxResults": max_results,
        }
        if sync_token:
            params["syncToken"] = sync_token
        else:
            if time_min_iso:
                params["timeMin"] = time_min_iso
            if time_max_iso:
                params["timeMax"] = time_max_iso
        if page_token:
            params["pageToken"] = page_token

        return await self._request(
            "GET",
            f"/calendars/{self._calendar_id}/events",
            params=params,
        )

    async def watch_events(
        self,
        *,
        channel_id: str,
        address: str,
        token: str | None = None,
        ttl_seconds: int | None = None,
    ) -> dict[str, Any]:
        """Register an events.watch push channel; returns id/resourceId/expiration."""
        body: dict[str, Any] = {"id": channel_id, "type": "web_hook", "address": address}
        if token:
            body["token"] = token
        if ttl_seconds:
            body["params"] = {"ttl": str(ttl_seconds)}
        return await self._request(
            "POST",
            f"/calendars/{self._calendar_id}/events/watch",
            json=body,
        )

    async def stop_channel(self, channel_id: str, resource_id: str) -> None:
        """Stop a previously-registered push channel."""
        try:
            await self._request(
                "POST",
                "/channels/stop",
                json={"id": channel_id, "resourceId": resource_id},
            )
        except GoogleCalendarNotFoundError:
            self._log.info("google_calendar_channel_already_stopped", channel_id=channel_id)
