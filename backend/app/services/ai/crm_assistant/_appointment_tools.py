"""Appointment CRM assistant tools."""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import select

from app.models.appointment import Appointment
from app.services.ai.crm_assistant._tool_context import CRMToolContext, ToolArguments, ToolHandler


class AppointmentAssistantTools:
    """Read appointment data for CRM assistant tool calls."""

    def __init__(self, context: CRMToolContext) -> None:
        self.context = context

    def handlers(self) -> dict[str, ToolHandler]:
        return {"list_appointments": self.list_appointments}

    async def list_appointments(self, args: ToolArguments) -> dict[str, object]:
        limit = min(args.get("limit", 10), 50)
        stmt = (
            select(Appointment)
            .where(
                Appointment.workspace_id == self.context.workspace_id,
                Appointment.scheduled_at >= datetime.now(UTC),
            )
            .order_by(Appointment.scheduled_at)
            .limit(limit)
        )
        result = await self.context.db.execute(stmt)
        appointments = result.scalars().all()

        return {
            "success": True,
            "data": [
                {
                    "id": appointment.id,
                    "contact_id": appointment.contact_id,
                    "scheduled_at": (
                        appointment.scheduled_at.isoformat() if appointment.scheduled_at else None
                    ),
                    "duration_minutes": appointment.duration_minutes,
                    "status": appointment.status,
                    "notes": appointment.notes,
                }
                for appointment in appointments
            ],
            "count": len(appointments),
        }
