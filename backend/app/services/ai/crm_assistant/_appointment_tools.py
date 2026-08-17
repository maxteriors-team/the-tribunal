"""Appointment and calendar-event CRM assistant tools."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from fastapi import HTTPException

from app.db.scope import get_workspace_owned, select_workspace_owned
from app.models.appointment import Appointment
from app.schemas.appointment import AppointmentCreate, AppointmentUpdate
from app.services.ai.crm_assistant._pagination import count_matching, listing
from app.services.ai.crm_assistant._tool_context import (
    CRMToolContext,
    ToolArguments,
    ToolHandler,
    without_confirmation,
)
from app.services.ai.crm_assistant._tool_errors import (
    invalid_argument,
    not_found,
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
        limit = min(max(int(args.get("limit", 10)), 1), 50)
        include_past = bool(args.get("include_past", False))
        stmt = select_workspace_owned(Appointment, self.context.workspace_id)
        if not include_past:
            stmt = stmt.where(Appointment.scheduled_at >= datetime.now(UTC))
        if contact_id := args.get("contact_id"):
            stmt = stmt.where(Appointment.contact_id == contact_id)
        if status := args.get("status"):
            stmt = stmt.where(Appointment.status == status)
        try:
            if date_from := args.get("date_from"):
                stmt = stmt.where(Appointment.scheduled_at >= datetime.fromisoformat(date_from))
            if date_to := args.get("date_to"):
                stmt = stmt.where(Appointment.scheduled_at <= datetime.fromisoformat(date_to))
        except (TypeError, ValueError):
            return invalid_argument("Invalid appointment date range.", "Use ISO 8601 datetimes.")

        total = await count_matching(self.context.db, Appointment, stmt)
        result = await self.context.db.execute(stmt.order_by(Appointment.scheduled_at).limit(limit))
        return listing(
            [self.serialize_appointment(appointment) for appointment in result.scalars().all()],
            total=total,
        )

    async def get_appointment(self, args: ToolArguments) -> dict[str, object]:
        appointment = await self._find(args.get("appointment_id"))
        if appointment is None:
            return not_found("Appointment", "Call list_appointments to get a valid id.")
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

    @staticmethod
    def _parse_id(raw_id: Any) -> int | None:
        try:
            appointment_id = int(raw_id)
        except (TypeError, ValueError):
            return None
        return appointment_id if appointment_id > 0 else None
