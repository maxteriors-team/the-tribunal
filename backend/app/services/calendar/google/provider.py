"""``GoogleCalendarProvider`` — the Google implementation of ``CalendarProvider``.

Composes the Google Calendar API client (events + free/busy) with the local
availability engine so booking code stays provider-neutral. Slots come from the
schedule config + live free/busy; bookings become Google events (with a Meet
link); cancel/reschedule map to delete/patch.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

import structlog

from app.services.calendar.google.availability import (
    ScheduleConfig,
    compute_available_slots,
)
from app.services.calendar.google.client import GoogleCalendarClient, GoogleCalendarError
from app.services.calendar.provider import ProviderBooking

logger = structlog.get_logger()

CALENDAR_PROVIDER_GOOGLE = "google"


class GoogleCalendarProvider:
    """Book against a workspace's Google Calendar via events + free/busy."""

    provider_name: str = CALENDAR_PROVIDER_GOOGLE

    def __init__(
        self,
        client: GoogleCalendarClient,
        schedule: ScheduleConfig,
        *,
        reschedule_link_base: str | None = None,
        owns_client: bool = True,
    ) -> None:
        self._client = client
        self._schedule = schedule
        self._reschedule_link_base = reschedule_link_base
        self._owns_client = owns_client
        self._log = logger.bind(component="google_calendar_provider")

    # ── availability ────────────────────────────────────────────────

    async def get_availability(
        self,
        start_date: datetime,
        end_date: datetime,
        timezone: str = "America/New_York",
    ) -> list[dict[str, Any]]:
        tz = self._schedule.zoneinfo()
        # Query free/busy across the whole day range (inclusive end day).
        window_start = start_date.astimezone(tz).replace(hour=0, minute=0, second=0, microsecond=0)
        window_end = end_date.astimezone(tz).replace(
            hour=0, minute=0, second=0, microsecond=0
        ) + timedelta(days=1)
        busy = await self._client.freebusy(
            time_min_iso=window_start.isoformat(),
            time_max_iso=window_end.isoformat(),
            timezone=self._schedule.timezone,
        )
        slots = compute_available_slots(
            schedule=self._schedule,
            start_date=start_date,
            end_date=end_date,
            busy_intervals=busy,
        )
        self._log.info("google_availability_computed", slot_count=len(slots))
        return list(slots)

    # ── booking ─────────────────────────────────────────────────────

    async def create_booking(
        self,
        *,
        start_time_iso: str,
        contact_email: str,
        contact_name: str,
        duration_minutes: int = 30,
        timezone: str = "America/New_York",
        metadata: dict[str, Any] | None = None,
        phone_number: str | None = None,
    ) -> ProviderBooking:
        # The incoming wall-clock time is the schedule's local time regardless of
        # how the caller tagged the offset: the voice path passes the engine's
        # local-offset ISO, the text path reconstructs a naive ``...Z`` string.
        # Re-anchor to the schedule timezone so both book the same local instant.
        start = self._localize(start_time_iso)
        end = start + timedelta(minutes=duration_minutes)
        start_iso = start.isoformat()
        end_iso = end.isoformat()

        # Double-book guard: re-check free/busy immediately before insert. Google
        # has no atomic "book if free"; we accept a small race and reconcile via
        # sync.
        busy = await self._client.freebusy(
            time_min_iso=start_iso,
            time_max_iso=end_iso,
            timezone=self._schedule.timezone,
        )
        if _overlaps(start, end, busy):
            raise GoogleCalendarError("Requested time is no longer available")

        private_props: dict[str, str] = {"source": "the-tribunal"}
        if metadata:
            for key, value in metadata.items():
                if value is not None:
                    private_props[str(key)] = str(value)
        if phone_number:
            private_props["attendee_phone"] = phone_number

        description = None
        if metadata and metadata.get("notes"):
            description = str(metadata["notes"])

        event = await self._client.insert_event(
            summary=f"Appointment with {contact_name}",
            start_iso=start_iso,
            end_iso=end_iso,
            timezone=self._schedule.timezone,
            attendee_email=contact_email,
            attendee_name=contact_name,
            description=description,
            add_meet=True,
            private_properties=private_props,
        )
        event_id = event.get("id")
        self._log.info("google_booking_created", event_id=event_id)
        return ProviderBooking(
            provider=self.provider_name,
            external_event_id=event_id,
            booking_uid=event_id,
            raw=event,
        )

    async def cancel_booking(
        self,
        external_event_id: str,
        *,
        reason: str = "Cancelled by customer",
    ) -> bool:
        await self._client.delete_event(external_event_id)
        return True

    async def reschedule_booking(
        self,
        external_event_id: str,
        *,
        start_time_iso: str,
        duration_minutes: int = 30,
        timezone: str = "America/New_York",
    ) -> ProviderBooking:
        start = self._localize(start_time_iso)
        end = start + timedelta(minutes=duration_minutes)
        event = await self._client.patch_event(
            external_event_id,
            start_iso=start.isoformat(),
            end_iso=end.isoformat(),
            timezone=self._schedule.timezone,
        )
        return ProviderBooking(
            provider=self.provider_name,
            external_event_id=event.get("id", external_event_id),
            booking_uid=event.get("id", external_event_id),
            raw=event,
        )

    def _localize(self, start_time_iso: str) -> datetime:
        """Return the wall-clock time of ``start_time_iso`` in the schedule timezone."""
        parsed = _parse_iso(start_time_iso)
        return parsed.replace(tzinfo=None).replace(tzinfo=self._schedule.zoneinfo())

    def reschedule_link(
        self,
        *,
        contact_email: str,
        contact_name: str,
        contact_phone: str | None = None,
    ) -> str:
        # Google has no hosted reschedule page; return our own reschedule flow
        # link when configured (wired in a later phase), else empty.
        return self._reschedule_link_base or ""

    async def close(self) -> None:
        if self._owns_client:
            await self._client.close()


# ── helpers ─────────────────────────────────────────────────────────


def _parse_iso(value: str) -> datetime:
    normalized = value.replace("Z", "+00:00") if value.endswith("Z") else value
    return datetime.fromisoformat(normalized)


def _overlaps(start: datetime, end: datetime, busy: list[dict[str, str]]) -> bool:
    for block in busy:
        try:
            busy_start = _parse_iso(block["start"])
            busy_end = _parse_iso(block["end"])
        except (KeyError, ValueError):
            continue
        if start < busy_end and busy_start < end:
            return True
    return False
