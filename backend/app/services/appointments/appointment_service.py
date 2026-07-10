"""Appointment business logic service."""

import uuid
from datetime import datetime
from typing import Any

import structlog
from fastapi import HTTPException, status
from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.db.pagination import paginate
from app.models.agent import Agent
from app.models.appointment import Appointment, AppointmentStatus
from app.models.campaign import Campaign
from app.models.contact import Contact
from app.models.workspace import Workspace
from app.schemas.appointment import (
    AppointmentAgentStat,
    AppointmentCampaignStat,
    AppointmentCreate,
    AppointmentOverallStats,
    AppointmentResponse,
    AppointmentStatsResponse,
    AppointmentUpdate,
    PaginatedAppointments,
)

logger = structlog.get_logger()


def _calc_show_up_rate(completed: int, no_show: int) -> float:
    """Return show-up rate as a percentage, or 0 when there is no data."""
    denom = completed + no_show
    if denom == 0:
        return 0.0
    return round(completed / denom * 100, 1)


class AppointmentService:
    """Service for appointment CRUD and stats.

    The local ``appointments`` table is the single source of truth; there is no
    external calendar sync.
    """

    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self.log = logger.bind(component="appointment_service")

    async def list_appointments(
        self,
        workspace_id: uuid.UUID,
        page: int = 1,
        page_size: int = 50,
        status_filter: str | None = None,
        contact_id: int | None = None,
        agent_id: str | None = None,
        date_from: datetime | None = None,
        date_to: datetime | None = None,
    ) -> PaginatedAppointments:
        """List appointments with optional filters."""
        query = (
            select(Appointment)
            .options(selectinload(Appointment.contact))
            .where(Appointment.workspace_id == workspace_id)
        )

        if status_filter:
            query = query.where(Appointment.status == status_filter)
        if contact_id is not None:
            query = query.where(Appointment.contact_id == contact_id)
        if agent_id is not None:
            query = query.where(Appointment.agent_id == uuid.UUID(agent_id))
        if date_from is not None:
            query = query.where(Appointment.scheduled_at >= date_from)
        if date_to is not None:
            query = query.where(Appointment.scheduled_at <= date_to)

        query = query.order_by(Appointment.scheduled_at.desc())
        result = await paginate(self.db, query, page=page, page_size=page_size, unique=True)

        return PaginatedAppointments(**result.to_response(AppointmentResponse))

    async def create_appointment(
        self,
        workspace_id: uuid.UUID,
        appointment_in: AppointmentCreate,
    ) -> Appointment:
        """Create a new appointment in the CRM (the single source of truth)."""
        log = self.log.bind(workspace_id=str(workspace_id), contact_id=appointment_in.contact_id)

        # Verify contact exists in workspace
        contact_result = await self.db.execute(
            select(Contact).where(
                Contact.id == appointment_in.contact_id,
                Contact.workspace_id == workspace_id,
            )
        )
        contact = contact_result.scalar_one_or_none()
        if not contact:
            log.warning("contact_not_found")
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Contact not found",
            )

        # Verify agent exists if provided
        agent = None
        if appointment_in.agent_id:
            agent_result = await self.db.execute(
                select(Agent).where(
                    Agent.id == uuid.UUID(appointment_in.agent_id),
                    Agent.workspace_id == workspace_id,
                )
            )
            agent = agent_result.scalar_one_or_none()
            if not agent:
                log.warning("agent_not_found")
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="Agent not found",
                )

        appointment = Appointment(
            workspace_id=workspace_id,
            agent_id=uuid.UUID(appointment_in.agent_id) if appointment_in.agent_id else None,
            **appointment_in.model_dump(exclude={"agent_id"}),
        )
        self.db.add(appointment)
        await self.db.commit()
        await self.db.refresh(appointment)

        log.info("appointment_created", appointment_id=appointment.id)

        return appointment

    async def get_appointment(
        self,
        workspace_id: uuid.UUID,
        appointment_id: int,
    ) -> Appointment:
        """Get an appointment by ID, raising 404 if not found.

        Eager-loads ``contact`` so ``AppointmentResponse`` can serialize the
        nested contact summary without triggering an async lazy-load (which
        raises ``MissingGreenlet``) after the request session has committed.
        """
        result = await self.db.execute(
            select(Appointment)
            .options(selectinload(Appointment.contact))
            .where(
                Appointment.id == appointment_id,
                Appointment.workspace_id == workspace_id,
            )
        )
        appointment = result.scalar_one_or_none()
        if not appointment:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Appointment not found",
            )
        return appointment

    async def update_appointment(
        self,
        workspace_id: uuid.UUID,
        appointment_id: int,
        appointment_in: AppointmentUpdate,
    ) -> Appointment:
        """Update an appointment's fields."""
        appointment = await self.get_appointment(workspace_id, appointment_id)

        previous_status = appointment.status
        update_data = appointment_in.model_dump(exclude_unset=True)
        for field, value in update_data.items():
            setattr(appointment, field, value)

        await self.db.commit()
        await self.db.refresh(appointment)

        self.log.info(
            "appointment_updated",
            workspace_id=str(workspace_id),
            appointment_id=appointment_id,
            status=appointment.status,
        )

        # When an operator marks a job completed, enqueue a review request.
        # No-ops unless the workspace enabled the reputation engine + auto
        # trigger. Never let a reputation hiccup fail the appointment update.
        if (
            previous_status != AppointmentStatus.COMPLETED
            and appointment.status == AppointmentStatus.COMPLETED
        ):
            try:
                from app.services.reviews import ReviewService

                await ReviewService(self.db).enqueue_for_appointment(appointment)
            except Exception as exc:  # noqa: BLE001 — reputation is best-effort
                self.log.warning("review_request_enqueue_failed", error=str(exc))

        return appointment

    async def delete_appointment(
        self,
        workspace_id: uuid.UUID,
        appointment_id: int,
    ) -> None:
        """Delete an appointment."""
        appointment = await self.get_appointment(workspace_id, appointment_id)
        await self.db.delete(appointment)
        await self.db.commit()
        self.log.info(
            "appointment_deleted",
            workspace_id=str(workspace_id),
            appointment_id=appointment_id,
        )

    async def get_stats(self, workspace_id: uuid.UUID) -> AppointmentStatsResponse:
        """Return show-up rate analytics (overall, by agent, by campaign)."""
        overall_result = await self.db.execute(
            select(
                func.count(Appointment.id).label("total"),
                func.count(case((Appointment.status == "scheduled", 1))).label("scheduled"),
                func.count(case((Appointment.status == "completed", 1))).label("completed"),
                func.count(case((Appointment.status == "no_show", 1))).label("no_show"),
                func.count(case((Appointment.status == "cancelled", 1))).label("cancelled"),
            ).where(Appointment.workspace_id == workspace_id)
        )
        row = overall_result.one()
        overall = AppointmentOverallStats(
            total=row.total,
            scheduled=row.scheduled,
            completed=row.completed,
            no_show=row.no_show,
            cancelled=row.cancelled,
            show_up_rate=_calc_show_up_rate(row.completed, row.no_show),
        )

        agent_rows_result = await self.db.execute(
            select(
                Appointment.agent_id,
                Agent.name.label("agent_name"),
                func.count(Appointment.id).label("total"),
                func.count(case((Appointment.status == "completed", 1))).label("completed"),
                func.count(case((Appointment.status == "no_show", 1))).label("no_show"),
            )
            .join(Agent, Appointment.agent_id == Agent.id, isouter=False)
            .where(
                Appointment.workspace_id == workspace_id,
                Appointment.agent_id.is_not(None),
            )
            .group_by(Appointment.agent_id, Agent.name)
            .order_by(func.count(Appointment.id).desc())
        )
        by_agent: list[AppointmentAgentStat] = [
            AppointmentAgentStat(
                agent_id=str(r.agent_id),
                agent_name=r.agent_name,
                total=r.total,
                completed=r.completed,
                no_show=r.no_show,
                show_up_rate=_calc_show_up_rate(r.completed, r.no_show),
            )
            for r in agent_rows_result.all()
        ]

        campaign_rows_result = await self.db.execute(
            select(
                Appointment.campaign_id,
                Campaign.name.label("campaign_name"),
                func.count(Appointment.id).label("total"),
                func.count(case((Appointment.status == "completed", 1))).label("completed"),
                func.count(case((Appointment.status == "no_show", 1))).label("no_show"),
            )
            .join(Campaign, Appointment.campaign_id == Campaign.id, isouter=False)
            .where(
                Appointment.workspace_id == workspace_id,
                Appointment.campaign_id.is_not(None),
            )
            .group_by(Appointment.campaign_id, Campaign.name)
            .order_by(func.count(Appointment.id).desc())
        )
        by_campaign: list[AppointmentCampaignStat] = [
            AppointmentCampaignStat(
                campaign_id=str(r.campaign_id),
                campaign_name=r.campaign_name,
                total=r.total,
                completed=r.completed,
                no_show=r.no_show,
                show_up_rate=_calc_show_up_rate(r.completed, r.no_show),
            )
            for r in campaign_rows_result.all()
        ]

        return AppointmentStatsResponse(
            overall=overall,
            by_agent=by_agent,
            by_campaign=by_campaign,
        )

    async def send_reminder(
        self,
        workspace_id: uuid.UUID,
        appointment_id: int,
        workspace: Workspace,
    ) -> dict[str, Any]:
        """Send an SMS reminder for a scheduled appointment."""
        from app.services.calendar import reminder_service

        appointment = await self.get_appointment(workspace_id, appointment_id)

        if appointment.status != "scheduled":
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Reminders can only be sent for scheduled appointments",
            )

        contact_result = await self.db.execute(
            select(Contact).where(Contact.id == appointment.contact_id)
        )
        contact = contact_result.scalar_one_or_none()
        if not contact:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Contact not found",
            )

        agent = None
        if appointment.agent_id is not None:
            agent_result = await self.db.execute(
                select(Agent).where(Agent.id == appointment.agent_id)
            )
            agent = agent_result.scalar_one_or_none()

        return await reminder_service.send_appointment_reminder(
            db=self.db,
            appointment=appointment,
            workspace=workspace,
            contact=contact,
            agent=agent,
        )
