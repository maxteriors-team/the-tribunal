"""Provider-neutral calendar abstraction.

Defines the :class:`CalendarProvider` protocol so booking code is agnostic to
the underlying scheduling backend (Cal.com today, Google Calendar during and
after the migration). Concrete implementations:

- ``CalComCalendarProvider`` (``app.services.calendar.calcom``) — adapts the
  existing ``CalComService`` and keeps current behavior.
- ``GoogleCalendarProvider`` (``app.services.calendar.google``) — Google
  Calendar events + a locally-built availability engine.

A provider instance is *bound* to the calendar/target it books against (a
Cal.com event type, or a Google calendar + schedule config). Callers therefore
never pass an ``event_type_id`` through the protocol — that binding lives inside
the concrete provider.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Protocol, runtime_checkable


@dataclass
class ProviderSlot:
    """A single available time slot, provider-neutral.

    ``iso`` is the fully-qualified start instant (RFC 3339). ``date`` is
    ``YYYY-MM-DD`` and ``time`` is ``HH:MM`` (24h) in the requested timezone.
    """

    date: str
    time: str
    iso: str = ""


@dataclass
class ProviderBooking:
    """Result of creating (or rescheduling) a booking, provider-neutral.

    ``external_event_id`` is the provider's canonical identifier for the created
    event (Cal.com booking UID, Google event id). ``booking_uid`` / ``booking_id``
    preserve the legacy Cal.com identifiers so existing persistence keeps working
    during the migration; new code should prefer ``external_event_id`` + ``provider``.
    """

    provider: str
    external_event_id: str | None = None
    booking_uid: str | None = None
    booking_id: int | None = None
    raw: dict[str, Any] = field(default_factory=dict)


@runtime_checkable
class CalendarProvider(Protocol):
    """Protocol every calendar backend implements.

    Availability returns raw slot dicts (``{"date", "time", "iso"}``) to match
    the shape ``BookingService`` already consumes; booking/reschedule return a
    normalized :class:`ProviderBooking`.
    """

    #: Short provider key persisted on the appointment (e.g. ``"calcom"``, ``"google"``).
    provider_name: str

    async def get_availability(
        self,
        start_date: datetime,
        end_date: datetime,
        timezone: str = "America/New_York",
    ) -> list[dict[str, Any]]:
        """Return bookable slots between ``start_date`` and ``end_date`` (inclusive)."""
        ...

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
        """Create an event/booking at ``start_time_iso`` and return its identifiers."""
        ...

    async def cancel_booking(
        self,
        external_event_id: str,
        *,
        reason: str = "Cancelled by customer",
    ) -> bool:
        """Cancel a previously created booking by its external id."""
        ...

    async def reschedule_booking(
        self,
        external_event_id: str,
        *,
        start_time_iso: str,
        duration_minutes: int = 30,
        timezone: str = "America/New_York",
    ) -> ProviderBooking:
        """Move an existing booking to a new start time."""
        ...

    def reschedule_link(
        self,
        *,
        contact_email: str,
        contact_name: str,
        contact_phone: str | None = None,
    ) -> str:
        """Return a self-service reschedule/booking URL for this contact."""
        ...

    async def close(self) -> None:
        """Release any underlying network resources."""
        ...
