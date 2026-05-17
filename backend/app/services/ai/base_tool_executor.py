"""Base tool executor with shared Cal.com booking logic.

Extracts duplicated booking workflow from VoiceToolExecutor and
TextToolExecutor into a single base class. Subclasses inject
channel-specific behavior via hook method overrides.

Usage:
    class MyExecutor(BaseToolExecutor):
        def format_availability_slots(self, slots, start_date):
            ...  # channel-specific formatting
"""

from typing import Any

import structlog

from app.core.config import settings
from app.services.calendar.booking import BookingService

logger = structlog.get_logger()


class BaseToolExecutor:
    """Base class for tool executors with shared Cal.com booking logic.

    Provides the core booking workflow (config validation, service
    instantiation, availability checks, appointment booking) while
    delegating channel-specific formatting and persistence to hook
    methods that subclasses override.
    """

    max_slots: int = 15
    pre_validate: bool = False

    def __init__(self, agent: Any, timezone: str = "America/New_York") -> None:
        self.agent = agent
        self.timezone = timezone
        self.log = logger.bind(service="base_tool_executor")

    # ── Config validation ───────────────────────────────────────────

    def _validate_calcom_config(self) -> dict[str, Any] | None:
        """Check Cal.com configuration. Returns error dict or None if valid."""
        if not self.agent or not self.agent.calcom_event_type_id:
            return {"success": False, "error": "Cal.com not configured for this agent"}
        if not settings.calcom_api_key:
            return {"success": False, "error": "Cal.com API key not configured"}
        return None

    def _create_booking_service(self) -> BookingService:
        """Create a BookingService with current agent config."""
        return BookingService(
            api_key=settings.calcom_api_key,
            event_type_id=self.agent.calcom_event_type_id,
            timezone=self.timezone,
        )

    # ── Shared tool implementations ─────────────────────────────────

    async def execute_check_availability(
        self,
        start_date_str: str,
        end_date_str: str | None,
    ) -> dict[str, Any]:
        """Check Cal.com availability. Delegates formatting to hooks."""
        error = self._validate_calcom_config()
        if error:
            return error

        booking_service = self._create_booking_service()
        try:
            result = await booking_service.check_availability(
                start_date_str=start_date_str,
                end_date_str=end_date_str,
                max_slots=self.max_slots,
            )

            if not result.success:
                return {"success": False, "error": result.error or "Unknown error"}

            if not result.slots:
                return {
                    "success": True,
                    "available": False,
                    "message": f"No available slots on {start_date_str}",
                }

            return self.format_availability_result(result.slots, start_date_str, end_date_str)

        finally:
            await booking_service.close()

    async def execute_book_appointment(
        self,
        date_str: str,
        time_str: str,
        email: str | None,
        duration_minutes: int = 30,
        notes: str | None = None,
    ) -> dict[str, Any]:
        """Book a Cal.com appointment. Delegates formatting/persistence to hooks."""
        error = self._validate_calcom_config()
        if error:
            return error

        if not email:
            return {
                "success": False,
                "error": "Email address is required for booking",
                "message": "Please ask the customer for their email address",
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
                pre_validate=self.pre_validate,
            )

            if not result.success:
                return self.format_booking_failure(result, time_str)

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

    # ── Hook methods (override in subclasses) ───────────────────────

    def get_contact_name(self) -> str:
        """Return customer name for booking. Override in subclass."""
        return "Customer"

    def get_contact_phone(self) -> str | None:
        """Return customer phone for booking. Override in subclass."""
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
        return {
            "success": True,
            "booking_uid": result.booking_uid,
        }

    def format_booking_failure(
        self,
        result: Any,
        time_str: str,
    ) -> dict[str, Any]:
        """Format failed booking response. Override in subclass."""
        return {"success": False, "error": result.error or "Booking failed"}

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
