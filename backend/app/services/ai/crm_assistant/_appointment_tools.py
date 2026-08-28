"""Appointment and calendar-event CRM assistant tools."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from fastapi import HTTPException

from app.core.permissions import appointment_owner_scope
from app.db.scope import get_workspace_owned
from app.models.appointment import Appointment
from app.schemas.appointment import AppointmentCreate, AppointmentUpdate
from app.services.ai.crm_assistant._pagination import listing
from app.services.ai.crm_assistant._tool_context import (
    CRMToolContext,
    ToolArguments,
    ToolHandler,
    without_confirmation,
)
from app.services.ai.crm_assistant._tool_errors import (
    invalid_argument,
    not_found,
    unavailable,
    validation_failed,
)
from app.services.appointments.appointment_service import AppointmentService


class AssistantAppointmentUpdate(AppointmentUpdate):
    """Assistant-only update fields, including calendar rescheduling."""

    scheduled_at: datetime | None = None


class AppointmentAssistantTools:
    """Read and manage workspace calendar appointments."""

    def __init__(self, context: CRMToolContext) -> None:
        self.context = context
        self.service = AppointmentService(context.db)

    def handlers(self) -> dict[str, ToolHandler]:
        return {
            "list_appointments": self.list_appointments,
            "get_appointment": self.get_appointment,
            "create_appointment": self.create_appointment,
            "update_appointment": self.update_appointment,
            "delete_appointment": self.delete_appointment,
        }

    @staticmethod
    def serialize_appointment(appointment: Appointment) -> dict[str, Any]:
        return {
            "id": appointment.id,
            "contact_id": appointment.contact_id,
            "scheduled_at": appointment.scheduled_at.isoformat(),
            "duration_minutes": appointment.duration_minutes,
            "service_type": appointment.service_type,
            "status": appointment.status,
            "notes": appointment.notes,
            "meeting_url": appointment.meeting_url,
            "calendar_event_url": appointment.google_calendar_event_url,
            "sync_status": appointment.sync_status,
        }

    async def list_appointments(self, args: ToolArguments) -> dict[str, object]:
        user_id = self._user_id()
        if user_id is None:
            return unavailable("An authenticated user is required for appointment access.")
        limit = args.get("limit", 10)
        if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 50:
            return invalid_argument("limit must be an integer between 1 and 50.")
        include_past = args.get("include_past", False)
        if not isinstance(include_past, bool):
            return invalid_argument("include_past must be a boolean.")
        try:
            date_from = datetime.fromisoformat(args["date_from"]) if args.get("date_from") else None
            date_to = datetime.fromisoformat(args["date_to"]) if args.get("date_to") else None
        except (TypeError, ValueError):
            return invalid_argument("Invalid appointment date range.", "Use ISO 8601 datetimes.")
        if date_from is not None and date_from.tzinfo is None:
            date_from = date_from.replace(tzinfo=UTC)
        if date_to is not None and date_to.tzinfo is None:
            date_to = date_to.replace(tzinfo=UTC)
        if not include_past:
            date_from = max(date_from or datetime.min.replace(tzinfo=UTC), datetime.now(UTC))
        if date_from is not None and date_to is not None and date_from > date_to:
            return invalid_argument("date_from must not be after date_to.")

        page = await self.service.list_appointments(
            workspace_id=self.context.workspace_id,
            page=1,
            page_size=limit,
            status_filter=args.get("status"),
            contact_id=args.get("contact_id"),
            date_from=date_from,
            date_to=date_to,
            visible_to_user_id=appointment_owner_scope(self.context.role, user_id),
        )
        return listing(
            [item.model_dump(mode="json") for item in page.items],
            total=page.total,
        )

    async def get_appointment(self, args: ToolArguments) -> dict[str, object]:
        user_id = self._user_id()
        if user_id is None:
            return unavailable("An authenticated user is required for appointment access.")
        appointment_id = self._parse_id(args.get("appointment_id"))
        if appointment_id is None:
            return invalid_argument("Invalid appointment_id.", "Use an integer appointment id.")
        try:
            appointment = await self.service.get_appointment(
                self.context.workspace_id,
                appointment_id,
                visible_to_user_id=appointment_owner_scope(self.context.role, user_id),
            )
        except HTTPException:
            return not_found("Appointment", "Call list_appointments to get a visible id.")
        return {"success": True, "data": self.serialize_appointment(appointment)}

    async def create_appointment(self, args: ToolArguments) -> dict[str, object]:
        try:
            appointment_in = AppointmentCreate(**without_confirmation(args))
            appointment = await AppointmentService(self.context.db).create_appointment(
                self.context.workspace_id,
                appointment_in,
            )
        except ValueError as exc:
            return validation_failed("Appointment", str(exc))
        except HTTPException as exc:
            return invalid_argument(str(exc.detail), "Check the contact and agent, then retry.")
        return {"success": True, "data": self.serialize_appointment(appointment)}

    async def update_appointment(self, args: ToolArguments) -> dict[str, object]:
        appointment_id = self._parse_id(args.get("appointment_id"))
        if appointment_id is None:
            return invalid_argument("Invalid appointment_id.", "Use an integer appointment id.")
        payload = without_confirmation(args)
        payload.pop("appointment_id", None)
        if not payload:
            return invalid_argument(
                "No appointment changes were provided.", "Provide a field to update."
            )
        try:
            appointment_in = AssistantAppointmentUpdate(**payload)
            appointment = await AppointmentService(self.context.db).update_appointment(
                self.context.workspace_id,
                appointment_id,
                appointment_in,
            )
        except ValueError as exc:
            return validation_failed("Appointment update", str(exc))
        except HTTPException as exc:
            return invalid_argument(str(exc.detail), "Check the appointment and retry.")
        return {"success": True, "data": self.serialize_appointment(appointment)}

    async def delete_appointment(self, args: ToolArguments) -> dict[str, object]:
        appointment_id = self._parse_id(args.get("appointment_id"))
        if appointment_id is None:
            return invalid_argument("Invalid appointment_id.", "Use an integer appointment id.")
        appointment = await self._find(appointment_id)
        if appointment is None:
            return not_found("Appointment", "Call list_appointments to get a valid id.")
        await AppointmentService(self.context.db).delete_appointment(
            self.context.workspace_id,
            appointment_id,
        )
        return {"success": True, "data": {"id": appointment_id, "deleted": True}}

    async def _find(self, raw_id: Any) -> Appointment | None:
        appointment_id = self._parse_id(raw_id)
        if appointment_id is None:
            return None
        return await get_workspace_owned(
            self.context.db,
            Appointment,
            appointment_id,
            self.context.workspace_id,
        )

    def _user_id(self) -> int | None:
        user_id = self.context.user_id
        return user_id if isinstance(user_id, int) and not isinstance(user_id, bool) else None

    @staticmethod
    def _parse_id(raw_id: Any) -> int | None:
        try:
            appointment_id = int(raw_id)
        except (TypeError, ValueError):
            return None
        return appointment_id if appointment_id > 0 else None
