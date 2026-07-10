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
from app.services.calendar.factory import get_calendar_provider
from app.services.calendar.google.oauth import google_oauth_configured

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
        # Staff member chosen by round-robin / skill-based routing for the most
        # recent booking attempt (None when the single-event-type path is used).
        self.assigned_staff: dict[str, Any] | None = None
        # Schedule config of the assigned staff member (Google slot engine input).
        self.assigned_schedule_config: dict[str, Any] | None = None
        # Cached per-instance "is this workspace on Google Calendar?" lookup.
        self._google_connected: bool | None = None

    # ── Config validation ───────────────────────────────────────────

    def _assignment_strategy(self) -> str:
        """Return the agent's booking assignment strategy (defaults to single)."""
        return getattr(self.agent, "assignment_strategy", "single") or "single"

    async def _workspace_has_google(self) -> bool:
        """Return whether this agent's workspace has a live Google Calendar connection."""
        if self._google_connected is not None:
            return self._google_connected
        workspace_id = getattr(self.agent, "workspace_id", None)
        if workspace_id is None or not google_oauth_configured():
            self._google_connected = False
            return False
        from app.db.session import AsyncSessionLocal
        from app.services.calendar.google.oauth import get_connection

        try:
            async with AsyncSessionLocal() as db:
                self._google_connected = await get_connection(db, workspace_id) is not None
        except Exception as e:  # pragma: no cover - defensive; treat as not connected
            self.log.warning("google_connection_check_failed", error=str(e))
            self._google_connected = False
        return self._google_connected

    def _validate_calcom_config(self) -> dict[str, Any] | None:
        """Check Cal.com configuration. Returns error dict or None if valid.

        With a multi-staff strategy the agent need not have its own
        ``calcom_event_type_id`` — the event type is resolved from the assigned
        staff member at booking time. Only the API key is strictly required up
        front; a missing event type surfaces after staff resolution.
        """
        if not settings.calcom_api_key:
            return {"success": False, "error": "Cal.com API key not configured"}
        if self._assignment_strategy() == "single" and (
            not self.agent or not self.agent.calcom_event_type_id
        ):
            return {"success": False, "error": "Cal.com not configured for this agent"}
        return None

    async def _validate_booking_config(self) -> dict[str, Any] | None:
        """Provider-neutral booking config check.

        When the workspace is on Google Calendar the Cal.com key/event-type are
        not required; otherwise the legacy Cal.com validation applies.
        """
        if await self._workspace_has_google():
            return None
        return self._validate_calcom_config()

    async def _resolve_event_type_id(
        self, required_skill: str | None, *, record: bool = True
    ) -> int | None:
        """Resolve which Cal.com event type to book against for this attempt.

        Applies the agent's assignment strategy: for round-robin / skill-based
        agents it picks a staff member from the pool and uses their event type,
        recording the choice in ``self.assigned_staff``. Falls back to the
        agent's own ``calcom_event_type_id`` when no staff is selected.

        ``record`` controls whether the selection consumes a round-robin turn.
        Bookings record (default); availability checks pass ``record=False`` so
        they only peek the staff member's event type without skewing
        distribution.
        """
        self.assigned_staff = None
        self.assigned_schedule_config = None
        strategy = self._assignment_strategy()
        default_event_type_id = getattr(self.agent, "calcom_event_type_id", None)
        if strategy == "single":
            return default_event_type_id

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
                if staff and (staff.calcom_event_type_id or staff.schedule_config):
                    self.assigned_staff = staff_to_assignment_dict(staff)
                    self.assigned_schedule_config = staff.schedule_config
                    return staff.calcom_event_type_id
        except Exception as e:  # pragma: no cover - defensive; fall back to default
            self.log.warning("staff_assignment_failed", error=str(e))

        return default_event_type_id

    async def _create_booking_service(self, event_type_id: int | None = None) -> BookingService:
        """Create a BookingService for the resolved (or agent default) event type.

        The concrete calendar provider is chosen by ``get_calendar_provider``
        (Cal.com today; Google when the workspace has a live connection). The
        assigned staff member's ``schedule_config`` (or the agent's) feeds the
        Google slot engine.
        """
        resolved = event_type_id or getattr(self.agent, "calcom_event_type_id", None)
        schedule_config = getattr(self, "assigned_schedule_config", None) or getattr(
            self.agent, "schedule_config", None
        )
        provider = await get_calendar_provider(
            event_type_id=resolved,
            agent=self.agent,
            workspace_id=getattr(self.agent, "workspace_id", None),
            schedule_config=schedule_config,
            timezone=self.timezone,
        )
        return BookingService(
            api_key=settings.calcom_api_key,
            event_type_id=resolved or 0,
            timezone=self.timezone,
            provider=provider,
        )

    # ── Shared tool implementations ─────────────────────────────────

    async def execute_check_availability(
        self,
        start_date_str: str,
        end_date_str: str | None,
        required_skill: str | None = None,
    ) -> dict[str, Any]:
        """Check calendar availability. Delegates formatting to hooks."""
        error = await self._validate_booking_config()
        if error:
            return error

        google_connected = await self._workspace_has_google()
        # Peek only: an availability check must not consume a round-robin turn.
        event_type_id = await self._resolve_event_type_id(required_skill, record=False)
        if not event_type_id and not google_connected:
            return {"success": False, "error": "No bookable calendar available"}

        booking_service = await self._create_booking_service(event_type_id)
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
        required_skill: str | None = None,
    ) -> dict[str, Any]:
        """Book an appointment. Delegates formatting/persistence to hooks."""
        error = await self._validate_booking_config()
        if error:
            return error

        if not email:
            return {
                "success": False,
                "error": "Email address is required for booking",
                "message": "Please ask the customer for their email address",
            }

        google_connected = await self._workspace_has_google()
        event_type_id = await self._resolve_event_type_id(required_skill)
        if not event_type_id and not google_connected:
            return {"success": False, "error": "No bookable calendar available"}

        contact_name = self.get_contact_name()
        contact_phone = self.get_contact_phone()
        metadata = self.get_booking_metadata(notes)

        booking_service = await self._create_booking_service(event_type_id)
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
