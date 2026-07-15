"""Self-contained booking service.

Availability and booking are computed entirely from the CRM: a workspace's
weekly business hours (``workspace.settings["business_hours"]``, or a sensible
default) minus its existing ``scheduled`` appointments. There is no external
calendar call — the local ``appointments`` table is the single source of truth.

Returns structured dataclasses; callers (the AI tool executors) handle
channel-specific formatting and persist the appointment row themselves.

Usage:
    service = BookingService(workspace_id, timezone="America/New_York")
    result = await service.check_availability("2026-01-15")
    booking = await service.book_appointment("2026-01-15", "14:00", "a@b.com", "Alice")
    await service.close()
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import AsyncSessionLocal
from app.models.appointment import Appointment, AppointmentStatus
from app.models.workspace import Workspace
from app.services.calendar.availability import (
    BusyInterval,
    compute_available_slots,
    parse_schedule,
)

logger = structlog.get_logger()


@dataclass
class AvailableSlot:
    """A single open time slot."""

    date: str
    time: str
    iso: str = ""


@dataclass
class AvailabilityResult:
    """Result of checking availability."""

    success: bool
    slots: list[AvailableSlot] = field(default_factory=list)
    error: str | None = None


@dataclass
class BookingResult:
    """Result of creating a booking.

    ``booking_uid``/``booking_id`` are kept for interface compatibility with the
    executor persistence hooks; for local bookings they are ``None`` (the CRM
    appointment row is the record).
    """

    success: bool
    booking_uid: str | None = None
    booking_id: int | None = None
    error: str | None = None
    alternative_slots: list[AvailableSlot] = field(default_factory=list)


class BookingService:
    """Channel-agnostic booking backed by CRM business hours + appointments.

    Args:
        workspace_id: Workspace whose business hours + appointments define
            availability.
        timezone: IANA timezone string (default: America/New_York).
        slot_minutes: Slot granularity for availability generation.
        session_factory: Optional async-session factory (for testing).
    """

    def __init__(
        self,
        workspace_id: uuid.UUID,
        timezone: str = "America/New_York",
        *,
        slot_minutes: int = 30,
        session_factory: Any = None,
    ) -> None:
        self._workspace_id = workspace_id
        self._timezone = timezone
        self._slot_minutes = slot_minutes
        self._session_factory = session_factory or AsyncSessionLocal
        self._log = logger.bind(service="booking_service")

    async def check_availability(
        self,
        start_date_str: str,
        end_date_str: str | None = None,
        *,
        max_slots: int = 15,
        now: datetime | None = None,
    ) -> AvailabilityResult:
        """Return open slots between two dates (inclusive), YYYY-MM-DD.

        Slots come from the workspace's business hours minus existing scheduled
        appointments in the range. Past slots (relative to ``now``, default the
        current clock) are excluded; ``now`` is injectable so callers and tests
        can compute availability deterministically.
        """
        tz = self._get_timezone()
        try:
            start_date = datetime.strptime(start_date_str, "%Y-%m-%d").date()
            end_date = (
                datetime.strptime(end_date_str, "%Y-%m-%d").date() if end_date_str else start_date
            )
        except ValueError as e:
            return AvailabilityResult(success=False, error=f"Invalid date format: {e}")

        try:
            async with self._session_factory() as db:
                schedule_setting = await self._load_business_hours(db)
                busy = await self._load_busy_intervals(db, start_date, end_date, tz)

            slots = compute_available_slots(
                schedule=parse_schedule(schedule_setting),
                tz=tz,
                start_date=start_date,
                end_date=end_date,
                busy=busy,
                slot_minutes=self._slot_minutes,
                max_slots=max_slots,
                now=now,
            )
            self._log.info("availability_computed", slot_count=len(slots))
            return AvailabilityResult(
                success=True,
                slots=[AvailableSlot(date=s.date, time=s.time, iso=s.iso) for s in slots],
            )
        except Exception as e:  # noqa: BLE001 — surface as a structured failure
            self._log.exception("check_availability_error", error=str(e))
            return AvailabilityResult(success=False, error=f"Failed to check availability: {e!s}")

    async def book_appointment(
        self,
        date_str: str,
        time_str: str,
        email: str,
        contact_name: str,
        duration_minutes: int = 30,
        metadata: dict[str, Any] | None = None,
        phone_number: str | None = None,
        *,
        pre_validate: bool = False,
    ) -> BookingResult:
        """Confirm a local booking.

        No external calendar is contacted — the caller persists the appointment
        row. When ``pre_validate`` is set (voice agents), the slot is re-checked
        against current availability and alternatives are returned if it was
        taken since it was offered.
        """
        try:
            self._get_timezone()
            datetime.strptime(f"{date_str} {time_str}", "%Y-%m-%d %H:%M")
        except ValueError as e:
            return BookingResult(success=False, error=f"Invalid date/time format: {e}")

        if pre_validate:
            availability = await self.check_availability(date_str, date_str, max_slots=50)
            if availability.success:
                still_open = any(s.time == time_str for s in availability.slots)
                if not still_open:
                    self._log.warning("booking_slot_unavailable", requested_time=time_str)
                    return BookingResult(
                        success=False,
                        error=f"The {time_str} slot is no longer available.",
                        alternative_slots=availability.slots[:5],
                    )

        self._log.info("booking_confirmed_local", date=date_str, time=time_str, email=email)
        return BookingResult(success=True, booking_uid=None, booking_id=None)

    async def close(self) -> None:
        """No external client to release."""
        return None

    async def _load_business_hours(self, db: AsyncSession) -> dict[str, Any] | None:
        """Load the workspace's stored ``business_hours`` setting, if any."""
        result = await db.execute(
            select(Workspace.settings).where(Workspace.id == self._workspace_id)
        )
        settings_row = result.scalar_one_or_none()
        if not settings_row:
            return None
        business_hours = settings_row.get("business_hours")
        return business_hours if isinstance(business_hours, dict) else None

    async def _load_busy_intervals(
        self,
        db: AsyncSession,
        start_date: Any,
        end_date: Any,
        tz: ZoneInfo,
    ) -> list[BusyInterval]:
        """Load scheduled appointments in range as busy intervals."""
        range_start = datetime.combine(start_date, datetime.min.time(), tzinfo=tz)
        range_end = datetime.combine(end_date, datetime.max.time(), tzinfo=tz)
        result = await db.execute(
            select(Appointment.scheduled_at, Appointment.duration_minutes).where(
                Appointment.workspace_id == self._workspace_id,
                Appointment.status == AppointmentStatus.SCHEDULED,
                Appointment.scheduled_at >= range_start,
                Appointment.scheduled_at <= range_end,
            )
        )
        intervals: list[BusyInterval] = []
        for scheduled_at, duration_minutes in result.all():
            start = scheduled_at.astimezone(tz)
            intervals.append(
                BusyInterval(start=start, end=start + timedelta(minutes=duration_minutes or 30))
            )
        return intervals

    def _get_timezone(self) -> ZoneInfo:
        """Return ZoneInfo for the configured timezone (default NY)."""
        try:
            return ZoneInfo(self._timezone)
        except ZoneInfoNotFoundError:
            return ZoneInfo("America/New_York")
