"""Shared booking service for Cal.com operations.

Extracts duplicated Cal.com booking logic from VoiceToolExecutor and
TextToolExecutor into a single, channel-agnostic service. Returns
structured dataclasses — callers handle channel-specific formatting
and DB persistence.

Usage:
    service = BookingService(api_key, event_type_id, timezone="America/New_York")
    result = await service.check_availability("2024-01-15")
    booking = await service.book_appointment("2024-01-15", "14:00", "a@b.com", "Alice")
    await service.close()
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import structlog

from app.services.calendar.calcom import CalComService

logger = structlog.get_logger()


@dataclass
class AvailableSlot:
    """A single available time slot from Cal.com."""

    date: str
    time: str
    iso: str = ""


@dataclass
class AvailabilityResult:
    """Result of checking Cal.com availability."""

    success: bool
    slots: list[AvailableSlot] = field(default_factory=list)
    error: str | None = None


@dataclass
class BookingResult:
    """Result of creating a Cal.com booking."""

    success: bool
    booking_uid: str | None = None
    booking_id: int | None = None
    error: str | None = None
    alternative_slots: list[AvailableSlot] = field(default_factory=list)


class BookingService:
    """Channel-agnostic Cal.com booking operations.

    Handles availability checks and appointment creation via CalComService.
    Returns structured dataclasses — callers handle formatting and DB work.

    Args:
        api_key: Cal.com API key
        event_type_id: Cal.com event type ID
        timezone: IANA timezone string (default: America/New_York)
        calcom_service: Optional CalComService instance (for testing)
    """

    def __init__(
        self,
        api_key: str,
        event_type_id: int,
        timezone: str = "America/New_York",
        calcom_service: CalComService | None = None,
    ) -> None:
        self._api_key = api_key
        self._event_type_id = event_type_id
        self._timezone = timezone
        self._calcom = calcom_service or CalComService(api_key)
        self._owns_calcom = calcom_service is None
        self._log = logger.bind(service="booking_service")

    async def check_availability(
        self,
        start_date_str: str,
        end_date_str: str | None = None,
        *,
        max_slots: int = 15,
    ) -> AvailabilityResult:
        """Check available time slots on Cal.com.

        Args:
            start_date_str: Start date in YYYY-MM-DD format
            end_date_str: Optional end date in YYYY-MM-DD format
            max_slots: Maximum number of slots to return (voice=10, text=15)

        Returns:
            AvailabilityResult with slots or error
        """
        try:
            tz = self._get_timezone()
            start_date = datetime.strptime(start_date_str, "%Y-%m-%d").replace(tzinfo=tz)
            end_date = (
                datetime.strptime(end_date_str, "%Y-%m-%d").replace(tzinfo=tz)
                if end_date_str
                else start_date
            )
        except ValueError as e:
            return AvailabilityResult(success=False, error=f"Invalid date format: {e}")

        try:
            raw_slots = await self._calcom.get_availability(
                event_type_id=self._event_type_id,
                start_date=start_date,
                end_date=end_date,
                timezone=self._timezone,
            )

            self._log.info("availability_fetched", slot_count=len(raw_slots))

            slots = [
                AvailableSlot(
                    date=s.get("date", ""),
                    time=s.get("time", ""),
                    iso=s.get("iso", ""),
                )
                for s in raw_slots[:max_slots]
            ]

            return AvailabilityResult(success=True, slots=slots)

        except Exception as e:
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
        """Book an appointment on Cal.com.

        Args:
            date_str: Date in YYYY-MM-DD format
            time_str: Time in HH:MM 24-hour format
            email: Customer email address
            contact_name: Customer name
            duration_minutes: Appointment duration
            metadata: Optional metadata dict for booking
            phone_number: Optional phone number (E.164)
            pre_validate: If True, re-check availability before booking
                (voice agents use True; text agents use False)

        Returns:
            BookingResult with booking IDs or error with alternatives
        """
        try:
            tz = self._get_timezone()
            start_date = datetime.strptime(date_str, "%Y-%m-%d").replace(tzinfo=tz)
        except ValueError as e:
            return BookingResult(success=False, error=f"Invalid date format: {e}")

        if pre_validate:
            # Re-check availability to confirm the slot still exists
            raw_slots = await self._calcom.get_availability(
                event_type_id=self._event_type_id,
                start_date=start_date,
                end_date=start_date,
                timezone=self._timezone,
            )

            matched_slot = next((s for s in raw_slots if s.get("time") == time_str), None)

            if not matched_slot:
                # Slot gone — return alternatives
                alternatives = [
                    AvailableSlot(
                        date=s.get("date", ""),
                        time=s.get("time", ""),
                        iso=s.get("iso", ""),
                    )
                    for s in raw_slots[:5]
                ]
                self._log.warning(
                    "booking_slot_unavailable",
                    requested_time=time_str,
                    available_count=len(raw_slots),
                )
                return BookingResult(
                    success=False,
                    error=f"The {time_str} slot is no longer available.",
                    alternative_slots=alternatives,
                )

            # Use the ISO time from the matched slot
            start_iso = matched_slot.get("iso", "") or f"{date_str}T{time_str}:00.000Z"
        else:
            # Text channel: construct ISO time directly
            start_iso = f"{date_str}T{time_str}:00.000Z"

        try:
            booking = await self._calcom.create_booking(
                event_type_id=self._event_type_id,
                contact_email=email,
                contact_name=contact_name,
                start_time_iso=start_iso,
                duration_minutes=duration_minutes,
                metadata=metadata,
                timezone=self._timezone,
                phone_number=phone_number,
            )

            booking_uid = booking.get("uid")
            booking_id = booking.get("id")

            self._log.info(
                "booking_created",
                booking_uid=booking_uid,
                booking_id=booking_id,
                email=email,
            )

            return BookingResult(
                success=True,
                booking_uid=booking_uid,
                booking_id=booking_id,
            )

        except Exception as e:
            self._log.exception("book_appointment_error", error=str(e))
            return BookingResult(success=False, error=f"Failed to book appointment: {e!s}")

    async def close(self) -> None:
        """Close the underlying CalComService if we own it."""
        if self._owns_calcom:
            await self._calcom.close()

    def _get_timezone(self) -> ZoneInfo:
        """Get ZoneInfo for configured timezone."""
        try:
            return ZoneInfo(self._timezone)
        except ZoneInfoNotFoundError:
            return ZoneInfo("America/New_York")
