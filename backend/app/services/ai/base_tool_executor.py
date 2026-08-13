"""Base tool executor with shared local booking logic.

Extracts the duplicated booking workflow from VoiceToolExecutor and
TextToolExecutor into a single base class. Subclasses inject
channel-specific behavior via hook method overrides.

Availability starts with workspace business hours and existing CRM appointments,
then subtracts conflicts from the assigned rep's connected Google Calendar.
Multi-staff round-robin/skill routing decides which rep/calendar is checked.

Usage:
    class MyExecutor(BaseToolExecutor):
        def format_availability_slots(self, slots, start_date):
            ...  # channel-specific formatting
"""

import uuid
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import structlog

from app.services.appointments.booking_validation import validate_booking_request
from app.services.calendar.booking import BookingResult, BookingService

logger = structlog.get_logger()

DEFAULT_BOOKING_TIMEZONE = "America/New_York"


class BaseToolExecutor:
    """Base class for tool executors with shared local booking logic.

    Provides the core booking workflow (staff assignment, service
    instantiation, availability checks, appointment booking) while
    delegating channel-specific formatting and persistence to hook
    methods that subclasses override.
    """

    max_slots: int = 15

    def __init__(self, agent: Any, timezone: str = "America/New_York") -> None:
        self.agent = agent
        self.timezone = timezone
        self.log = logger.bind(service="base_tool_executor")
        # Staff member chosen by round-robin / skill-based routing for the most
        # recent booking attempt.
        self.assigned_staff: dict[str, Any] | None = None
        self._booked_appointment: Any | None = None

    # ── Config validation ───────────────────────────────────────────

    def _assignment_strategy(self) -> str:
        """Return the agent's booking assignment strategy (defaults to single)."""
        return getattr(self.agent, "assignment_strategy", "single") or "single"

    def _get_timezone(self) -> ZoneInfo:
        """Return ZoneInfo for the configured timezone (default NY).

        The ``date``/``time`` arguments the model passes to ``book_appointment``
        are wall-clock times in *this* zone, because that is the zone
        ``BookingService`` generated the offered slots in. Anything that turns
        those strings into a ``datetime`` must attach this tzinfo — stamping
        them UTC silently shifts every booking by the UTC offset.
        """
        try:
            return ZoneInfo(self.timezone)
        except (ZoneInfoNotFoundError, ValueError):
            return ZoneInfo(DEFAULT_BOOKING_TIMEZONE)

    async def _resolve_assigned_staff(
        self, required_skill: str | None, *, record: bool = True
    ) -> None:
        """Assign a staff member for this booking attempt.

        Every agent selects from its own pool plus workspace-level Team resources.
        A selected login-backed row determines whose Google Calendar is checked
        and receives the confirmed event; its id is persisted on the appointment.

        ``record`` controls whether the selection consumes a round-robin turn.
        Bookings record (default); availability checks pass ``record=False`` so
        they only peek without skewing distribution.
        """
        self.assigned_staff = None

        from app.db.session import AsyncSessionLocal
        from app.services.calendar.staff_assignment import (
            resolve_staff_for_booking,
            staff_to_assignment_dict,
        )

        try:
            async with AsyncSessionLocal() as db:
                staff = await resolve_staff_for_booking(
                    db,
                    agent=self.agent,
                    required_skill=required_skill,
                    commit=True,
                    record=record,
                )
                if staff:
                    self.assigned_staff = staff_to_assignment_dict(staff)
        except Exception as e:  # pragma: no cover - defensive; fall back to no staff
            self.log.warning("staff_assignment_failed", error=str(e))

    def assigned_staff_id(self) -> uuid.UUID | None:
        """Return the staff member already routed for this booking, if any.

        Booking passes this to the finalizer rather than letting it re-resolve:
        a second resolution would consume another round-robin turn and could
        pick a different rep than the one the customer was quoted.
        """
        raw_id = (self.assigned_staff or {}).get("id")
        if not raw_id:
            return None
        try:
            return uuid.UUID(str(raw_id))
        except (ValueError, TypeError):
            self.log.warning("assigned_staff_id_invalid", raw_id=str(raw_id))
            return None

    def _create_booking_service(self) -> BookingService:
        """Create a local BookingService scoped to the agent's workspace."""
        return BookingService(
            workspace_id=self.agent.workspace_id,
            timezone=self.timezone,
        )

    # ── Shared tool implementations ─────────────────────────────────

    async def execute_check_availability(
        self,
        start_date_str: str,
        end_date_str: str | None,
        required_skill: str | None = None,
        duration_minutes: int = 30,
    ) -> dict[str, Any]:
        """Check local availability. Delegates formatting to hooks."""
        # Peek only: an availability check must not consume a round-robin turn.
        await self._resolve_assigned_staff(required_skill, record=False)

        booking_service = self._create_booking_service()
        try:
            result = await booking_service.check_availability(
                start_date_str=start_date_str,
                end_date_str=end_date_str,
                max_slots=self.max_slots,
                meeting_minutes=duration_minutes,
            )

            if not result.success:
                return {"success": False, "error": result.error or "Unknown error"}

            slots = await self._remove_google_calendar_conflicts(
                result.slots,
                duration_minutes=duration_minutes,
            )

            if not slots:
                return {
                    "success": True,
                    "available": False,
                    "message": f"No available slots on {start_date_str}",
                }

            return self.format_availability_result(slots, start_date_str, end_date_str)

        finally:
            await booking_service.close()

    async def execute_book_appointment(  # noqa: PLR0911
        self,
        date_str: str,
        time_str: str,
        email: str | None,
        duration_minutes: int = 30,
        notes: str | None = None,
        required_skill: str | None = None,
        service_type: str | None = None,
    ) -> dict[str, Any]:
        """Book an appointment locally. Delegates formatting/persistence to hooks.

        Validates the request *before* the booking service runs, because the
        agent confirms to the customer off this return value: anything not
        rejected here becomes a promise we cannot keep.
        """
        if not email:
            return {
                "success": False,
                "error": "Email address is required for booking",
                "message": "Please ask the customer for their email address",
            }

        validation = validate_booking_request(
            date_str=date_str,
            time_str=time_str,
            email=email,
            duration_minutes=duration_minutes,
            tz=self._get_timezone(),
            service_type=service_type or self.get_service_type(),
            contact_address=self.get_contact_address(),
        )
        if not validation.valid:
            self.log.info(
                "booking_request_rejected",
                error=validation.error,
                date=date_str,
                time=time_str,
            )
            return self.format_booking_failure(
                BookingResult(
                    success=False,
                    error=validation.error,
                    message=validation.message,
                ),
                time_str,
            )

        await self._resolve_assigned_staff(required_skill)
        raw_user_id = (self.assigned_staff or {}).get("user_id")
        if not raw_user_id:
            return {
                "success": False,
                "error": "No connected sales calendar is available",
                "message": "Please ask the team to connect a bookable Google Calendar",
            }

        slot_start = datetime.strptime(f"{date_str} {time_str}", "%Y-%m-%d %H:%M").replace(
            tzinfo=self._get_timezone()
        )
        try:
            from datetime import timedelta

            from app.db.session import AsyncSessionLocal
            from app.services.google_calendar import GoogleCalendarError, is_time_available

            async with AsyncSessionLocal() as calendar_db:
                google_slot_open = await is_time_available(
                    calendar_db,
                    user_id=int(raw_user_id),
                    starts_at=slot_start,
                    ends_at=slot_start + timedelta(minutes=duration_minutes),
                )
        except GoogleCalendarError as exc:
            return {"success": False, "error": str(exc), "message": str(exc)}
        if not google_slot_open:
            return {
                "success": False,
                "error": "That time is no longer available",
                "message": "Please offer another available time",
            }

        contact_name = self.get_contact_name()
        contact_phone = self.get_contact_phone()
        metadata = self.get_booking_metadata(notes)

        booking_service = self._create_booking_service()
        try:
            result = await booking_service.book_appointment(
                date_str=date_str,
                time_str=time_str,
                email=email,
                contact_name=contact_name,
                duration_minutes=duration_minutes,
                metadata=metadata,
                phone_number=contact_phone,
                service_type=service_type or self.get_service_type(),
            )

            if not result.success:
                return self.format_booking_failure(result, time_str)

            self._booked_appointment = None
            await self.post_booking_success(
                result,
                date_str,
                time_str,
                email,
                duration_minutes,
                notes,
            )

            return self.format_booking_success(
                result,
                contact_name,
                date_str,
                time_str,
                email,
                duration_minutes,
            )

        finally:
            await booking_service.close()

    async def _remove_google_calendar_conflicts(
        self,
        slots: list[Any],
        *,
        duration_minutes: int,
    ) -> list[Any]:
        """Remove busy slots from the routed rep's connected Google Calendar."""
        raw_user_id = (self.assigned_staff or {}).get("user_id")
        if not slots:
            return slots
        if not raw_user_id:
            return []

        from datetime import timedelta

        from app.db.session import AsyncSessionLocal
        from app.services.google_calendar import GoogleCalendarError, filter_available_slots

        parsed: list[tuple[Any, datetime]] = []
        timezone = self._get_timezone()
        for slot in slots:
            try:
                starts_at = datetime.fromisoformat(str(slot.iso))
                if starts_at.tzinfo is None:
                    starts_at = starts_at.replace(tzinfo=timezone)
                parsed.append((slot, starts_at))
            except (TypeError, ValueError):
                self.log.warning("availability_slot_invalid", slot_iso=str(slot.iso))

        if not parsed:
            return []
        try:
            async with AsyncSessionLocal() as db:
                available_times = await filter_available_slots(
                    db,
                    user_id=int(raw_user_id),
                    slots=[starts_at for _, starts_at in parsed],
                    duration=timedelta(minutes=duration_minutes),
                    timezone=self.timezone,
                )
        except GoogleCalendarError as exc:
            # Never advertise unverified availability: a disconnected calendar must
            # be fixed by the rep rather than risk a double-booking.
            self.log.info("google_calendar_conflicts_not_checked", error=str(exc))
            return []

        available = set(available_times)
        return [slot for slot, starts_at in parsed if starts_at in available]

    # ── Hook methods (override in subclasses) ───────────────────────

    def get_contact_name(self) -> str:
        """Return customer name for booking. Override in subclass."""
        return "Customer"

    def get_contact_phone(self) -> str | None:
        """Return customer phone for booking. Override in subclass."""
        return None

    def get_contact_address(self) -> str | None:
        """Return the customer's service address, if known. Override in subclass."""
        return None

    def get_service_type(self) -> str | None:
        """Return the service being booked, if known. Override in subclass."""
        return None

    def get_booking_metadata(self, notes: str | None) -> dict[str, Any] | None:
        """Return metadata dict for the booking. Override in subclass."""
        return {"notes": notes} if notes else None

    def format_availability_result(
        self,
        slots: list[Any],
        start_date_str: str,
        end_date_str: str | None,
    ) -> dict[str, Any]:
        """Format availability slots for channel. Override in subclass."""
        return {
            "success": True,
            "available": True,
            "slots": [{"date": s.date, "time": s.time, "iso": s.iso} for s in slots],
        }

    def format_booking_success(
        self,
        result: Any,
        contact_name: str,
        date_str: str,
        time_str: str,
        email: str,
        duration_minutes: int,
    ) -> dict[str, Any]:
        """Format successful booking response. Override in subclass."""
        return {"success": True}

    def format_booking_failure(
        self,
        result: Any,
        time_str: str,
    ) -> dict[str, Any]:
        """Format failed booking response. Override in subclass."""
        return {
            "success": False,
            "error": result.error or "Booking failed",
            "message": getattr(result, "message", None) or result.error or "Booking failed",
        }

    async def post_booking_success(
        self,
        result: Any,
        date_str: str,
        time_str: str,
        email: str,
        duration_minutes: int,
        notes: str | None,
    ) -> None:
        """Post-processing after successful booking. Override in subclass."""

    async def post_booking_attempt(self, success: bool) -> None:
        """Called after any booking attempt (success or failure). Override in subclass."""
