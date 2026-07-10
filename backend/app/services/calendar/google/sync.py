"""Incremental Google Calendar -> appointment status sync.

Replaces Cal.com's signed webhooks. Pulls changed events with
``events.list(syncToken)`` and maps them onto ``AppointmentStatus``:

- event ``status == "cancelled"``  -> appointment CANCELLED
- event start moved                -> appointment rescheduled (update
  ``scheduled_at`` + reset reminder tracking so reminders re-fire)

Driven by the polling worker (dev-friendly, no public webhook) and by the
push webhook when a watch channel is registered. Both paths are idempotent.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import AsyncSessionLocal
from app.models.appointment import Appointment, AppointmentStatus
from app.models.calendar_connection import CalendarConnection
from app.services.calendar.google.client import (
    GoogleCalendarClient,
    GoogleCalendarSyncTokenError,
)
from app.services.calendar.google.oauth import PROVIDER, make_token_provider

logger = structlog.get_logger()

_TERMINAL_STATUSES = (AppointmentStatus.COMPLETED, AppointmentStatus.CANCELLED)


async def sync_all_connections() -> dict[str, int]:
    """Sync every active Google connection. Returns aggregate counters."""
    log = logger.bind(component="google_calendar_sync")
    totals = {"connections": 0, "changed": 0}
    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(CalendarConnection).where(
                CalendarConnection.provider == PROVIDER,
                CalendarConnection.is_active.is_(True),
            )
        )
        connections = list(result.scalars().all())
        for connection in connections:
            totals["connections"] += 1
            try:
                changed = await sync_connection(db, connection)
                totals["changed"] += changed
            except Exception:  # noqa: BLE001 - one bad connection must not stop others
                log.exception(
                    "google_calendar_sync_connection_failed",
                    workspace_id=str(connection.workspace_id),
                )
    return totals


async def sync_workspace(workspace_id: uuid.UUID) -> int:
    """Sync a single workspace's Google connection (used by the push webhook)."""
    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(CalendarConnection).where(
                CalendarConnection.workspace_id == workspace_id,
                CalendarConnection.provider == PROVIDER,
                CalendarConnection.is_active.is_(True),
            )
        )
        connection = result.scalar_one_or_none()
        if connection is None:
            return 0
        return await sync_connection(db, connection)


async def sync_connection(db: AsyncSession, connection: CalendarConnection) -> int:
    """Pull incremental changes for one connection and apply them.

    Returns the number of appointments changed. Persists the new sync token.
    """
    log = logger.bind(component="google_calendar_sync", workspace_id=str(connection.workspace_id))
    token_provider = make_token_provider(connection.workspace_id)
    client = GoogleCalendarClient(token_provider, connection.google_calendar_id or "primary")
    try:
        try:
            events, new_sync_token = await _fetch_changes(client, connection.sync_token)
        except GoogleCalendarSyncTokenError:
            log.info("google_calendar_sync_token_expired_rebaselining")
            connection.sync_token = None
            events, new_sync_token = await _fetch_changes(client, None)
    finally:
        await client.close()

    changed = 0
    for event in events:
        if await _apply_event_change(db, connection.workspace_id, event, log):
            changed += 1

    connection.sync_token = new_sync_token
    await db.commit()
    if changed:
        log.info("google_calendar_sync_applied", changed=changed)
    return changed


async def _fetch_changes(
    client: GoogleCalendarClient, sync_token: str | None
) -> tuple[list[dict[str, Any]], str | None]:
    """Page through events.list, returning (changed events, next sync token)."""
    events: list[dict[str, Any]] = []
    page_token: str | None = None
    # Baseline sync (no token) only needs future events; existing ones already
    # match our appointments and produce no change.
    time_min_iso = None if sync_token else datetime.now(UTC).isoformat()
    new_sync_token: str | None = None

    while True:
        page = await client.list_events(
            sync_token=sync_token,
            time_min_iso=time_min_iso,
            page_token=page_token,
        )
        events.extend(page.get("items", []) or [])
        page_token = page.get("nextPageToken")
        if not page_token:
            new_sync_token = page.get("nextSyncToken")
            break

    return events, new_sync_token


async def _apply_event_change(
    db: AsyncSession,
    workspace_id: uuid.UUID,
    event: dict[str, Any],
    log: Any,
) -> bool:
    """Map one changed Google event onto its appointment. Returns True if changed."""
    event_id = event.get("id")
    if not event_id:
        return False

    result = await db.execute(
        select(Appointment).where(
            Appointment.workspace_id == workspace_id,
            Appointment.calendar_provider == PROVIDER,
            Appointment.external_event_id == event_id,
        )
    )
    appointment = result.scalar_one_or_none()
    if appointment is None:
        return False

    now = datetime.now(UTC)
    status = event.get("status")

    if status == "cancelled":
        if appointment.status in _TERMINAL_STATUSES:
            return False
        appointment.status = AppointmentStatus.CANCELLED
        appointment.sync_status = "synced"
        appointment.last_synced_at = now
        log.info("google_event_cancelled", appointment_id=appointment.id)
        return True

    new_start = _parse_event_start(event)
    if new_start is not None and not _same_instant(new_start, appointment.scheduled_at):
        appointment.scheduled_at = new_start
        # Re-arm reminders for the new time.
        appointment.reminder_sent_at = None
        appointment.sync_status = "synced"
        appointment.last_synced_at = now
        log.info(
            "google_event_rescheduled",
            appointment_id=appointment.id,
            new_start=new_start.isoformat(),
        )
        return True

    return False


def _parse_event_start(event: dict[str, Any]) -> datetime | None:
    start = event.get("start")
    if not isinstance(start, dict):
        return None
    value = start.get("dateTime") or start.get("date")
    if not value:
        return None
    try:
        normalized = value.replace("Z", "+00:00") if value.endswith("Z") else value
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed


def _same_instant(a: datetime, b: datetime) -> bool:
    return a.astimezone(UTC) == b.astimezone(UTC)
