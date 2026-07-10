"""Google Calendar watch-channel renewal worker.

``events.watch`` push channels expire (<= 7 days), so they must be periodically
re-registered. This worker (re-)registers a channel for each active connection
whose channel is missing or nearing expiry, pointing Google at our public
webhook. It is a no-op when no public backend URL is configured (dev), where the
polling sync worker keeps appointments in sync instead.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from urllib.parse import urlparse

from sqlalchemy import select

from app.core.config import settings
from app.db.session import AsyncSessionLocal
from app.models.calendar_connection import CalendarConnection
from app.services.calendar.google.client import GoogleCalendarClient
from app.services.calendar.google.oauth import (
    PROVIDER,
    google_oauth_configured,
    make_token_provider,
)
from app.workers.base import BaseWorker, WorkerRegistry

# Google caps channel TTL at 7 days; request just under and renew with headroom.
_WATCH_TTL_SECONDS = 7 * 24 * 3600
_RENEW_BEFORE = timedelta(days=1)


class GoogleCalendarWatchWorker(BaseWorker):
    """Register / renew Google Calendar push channels for active connections."""

    POLL_INTERVAL_SECONDS = settings.google_calendar_watch_renewal_poll_interval
    COMPONENT_NAME = "google_calendar_watch_renewal"
    MAX_CONCURRENCY = 1

    async def _process_items(self) -> None:
        if not google_oauth_configured():
            return
        address = _watch_address()
        if address is None:
            # No public webhook URL — polling sync worker handles changes.
            return

        renewed = 0
        async with AsyncSessionLocal() as db:
            result = await db.execute(
                select(CalendarConnection).where(
                    CalendarConnection.provider == PROVIDER,
                    CalendarConnection.is_active.is_(True),
                )
            )
            for connection in result.scalars().all():
                if not _needs_renewal(connection):
                    continue
                try:
                    await _register_watch(connection, address)
                    renewed += 1
                except Exception:  # noqa: BLE001 - one failure must not stop the rest
                    self.logger.exception(
                        "google_calendar_watch_register_failed",
                        workspace_id=str(connection.workspace_id),
                    )
            await db.commit()

        if renewed:
            self.record_items_processed(renewed)
            self.logger.info("google_calendar_watch_renewed", renewed=renewed)


def _needs_renewal(connection: CalendarConnection) -> bool:
    if not connection.watch_channel_id or connection.watch_expiration is None:
        return True
    return datetime.now(UTC) >= (connection.watch_expiration - _RENEW_BEFORE)


async def _register_watch(connection: CalendarConnection, address: str) -> None:
    token_provider = make_token_provider(connection.workspace_id)
    client = GoogleCalendarClient(token_provider, connection.google_calendar_id or "primary")
    channel_id = uuid.uuid4().hex
    try:
        response = await client.watch_events(
            channel_id=channel_id,
            address=address,
            token=channel_id,
            ttl_seconds=_WATCH_TTL_SECONDS,
        )
    finally:
        await client.close()

    connection.watch_channel_id = channel_id
    connection.watch_resource_id = response.get("resourceId")
    expiration = response.get("expiration")
    connection.watch_expiration = _expiration_to_datetime(expiration)


def _expiration_to_datetime(expiration: object) -> datetime | None:
    try:
        millis = int(str(expiration))
    except (TypeError, ValueError):
        return None
    return datetime.fromtimestamp(millis / 1000, tz=UTC)


def _watch_address() -> str | None:
    """Return the public webhook URL for Google to POST to, or None in dev."""
    for base in (settings.api_base_url, settings.public_base_url):
        candidate = (base or "").strip()
        if not candidate or _is_local_url(candidate):
            continue
        return f"{candidate.rstrip('/')}/webhooks/google-calendar/notifications"
    return None


def _is_local_url(value: str) -> bool:
    hostname = urlparse(value).hostname or ""
    return hostname in {"localhost", "127.0.0.1", "0.0.0.0"}


_registry = WorkerRegistry(GoogleCalendarWatchWorker)
start_google_calendar_watch_worker = _registry.start
stop_google_calendar_watch_worker = _registry.stop
get_google_calendar_watch_worker = _registry.get
