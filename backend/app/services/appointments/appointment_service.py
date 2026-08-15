"""Appointment business logic service."""

import uuid
from datetime import UTC, datetime
from typing import Any

import structlog
from fastapi import HTTPException, status
from sqlalchemy import ColumnElement, and_, case, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.db.pagination import paginate
from app.db.scope import assert_workspace_owned
from app.models.agent import Agent
from app.models.appointment import Appointment, AppointmentStatus
from app.models.bookable_staff import BookableStaff
from app.models.campaign import Campaign
from app.models.contact import Contact
from app.models.field_service import BusinessLocation
from app.models.user import User
from app.models.workspace import Workspace, WorkspaceMembership
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
from app.services.appointments.attendance import record_attendance_outcome
from app.services.appointments.external_sync import (
    delete_external_events,
    delete_google_calendar_event,
    update_external_events,
)
from app.utils.meeting_urls import zoom_meeting_id_from_url

logger = structlog.get_logger()


def _calc_show_up_rate(completed: int, no_show: int) -> float:
    """Return show-up rate as a percentage, or 0 when there is no data."""
    denom = completed + no_show
    if denom == 0:
        return 0.0
    return round(completed / denom * 100, 1)


class AppointmentService:
    """Service for appointment CRUD, user assignment, sync, and stats.

    The local ``appointments`` table is the source of truth; Google Calendar and
    Zoom synchronization are best-effort mirrors that never block local lifecycle
    changes.
    """

    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self.log = logger.bind(component="appointment_service")

    @staticmethod
    def booked_for_user_predicate(workspace_id: uuid.UUID, user_id: int) -> ColumnElement[bool]:
        """SQL predicate matching only the appointments ``user_id`` is booked on.

        The appointment counterpart of
        :meth:`app.services.jobs.job_service.JobService.assigned_job_predicate`:
        an appointment is theirs when its bookable-staff row is linked to their
        login (``bookable_staff.user_id``).

        Quiet and fail-closed: someone with no linked staff row simply matches
        nothing, which reads as an empty calendar rather than an error — the
        same failure mode an unlinked technician already has on the job board.
        """
        return Appointment.bookable_staff_id.in_(
            select(BookableStaff.id).where(
                BookableStaff.workspace_id == workspace_id,
                BookableStaff.user_id == user_id,
                BookableStaff.is_active.is_(True),
            )
        )

    async def _active_staff_for_user(
        self, workspace_id: uuid.UUID, user_id: int
    ) -> BookableStaff | None:
        result = await self.db.execute(
            select(BookableStaff)
            .where(
                BookableStaff.workspace_id == workspace_id,
                BookableStaff.user_id == user_id,
                BookableStaff.is_active.is_(True),
            )
            .order_by(BookableStaff.priority.desc(), BookableStaff.created_at.asc())
            .limit(1)
        )
        return result.scalar_one_or_none()

    async def _get_assignable_staff(
        self, workspace_id: uuid.UUID, staff_id: uuid.UUID
    ) -> BookableStaff:
        """Resolve an active login-backed staff row without crossing tenants."""
        result = await self.db.execute(
            select(BookableStaff)
            .join(User, User.id == BookableStaff.user_id)
            .join(
                WorkspaceMembership,
                and_(
                    WorkspaceMembership.workspace_id == workspace_id,
                    WorkspaceMembership.user_id == BookableStaff.user_id,
                ),
            )
            .where(
                BookableStaff.id == staff_id,
                BookableStaff.workspace_id == workspace_id,
                BookableStaff.is_active.is_(True),
                User.is_active.is_(True),
            )
        )
        staff = result.scalar_one_or_none()
        if staff is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Booking-enabled user not found",
            )
        return staff

    async def _sync_assigned_external_events(
        self,
        appointment: Appointment,
        *,
        contact: Contact,
        staff: BookableStaff,
    ) -> None:
        from app.services.appointments.booking_finalizer import (
            sync_appointment_external_events,
        )

        workspace = await self.db.get(Workspace, appointment.workspace_id)
        await sync_appointment_external_events(
            self.db,
            appointment=appointment,
            contact=contact,
            workspace=workspace,
            staff=staff,
            log=self.log.bind(appointment_id=appointment.id),
        )

    async def _prepare_staff_reassignment(
        self,
        appointment: Appointment,
        workspace_id: uuid.UUID,
        update_data: dict[str, Any],
    ) -> tuple[BookableStaff | None, bool]:
        if "bookable_staff_id" not in update_data:
            return None, False

        next_staff_id = update_data["bookable_staff_id"]
        assigned_staff = (
            await self._get_assignable_staff(workspace_id, next_staff_id)
            if next_staff_id is not None
            else None
        )
        if next_staff_id == appointment.bookable_staff_id:
            return assigned_staff, False

        # A Google event belongs to its old owner's calendar. Remove only that
        # mirror before changing owners; a workspace Zoom meeting remains valid.
        had_google_event = appointment.google_calendar_event_id is not None
        if had_google_event:
            await delete_google_calendar_event(self.db, appointment=appointment, log=self.log)
            appointment.google_calendar_event_id = None
            appointment.google_calendar_event_url = None
            if zoom_meeting_id_from_url(appointment.meeting_url) is None:
                appointment.meeting_url = None
            appointment.last_synced_at = None
            appointment.sync_status = "pending" if assigned_staff else "not_connected"
            appointment.sync_error = None if assigned_staff else "No booking-enabled user is tagged"
        return assigned_staff, True

    async def list_appointments(
        self,
        workspace_id: uuid.UUID,
        page: int = 1,
        page_size: int = 50,
        status_filter: str | None = None,
        contact_id: int | None = None,
        agent_id: str | None = None,
        business_location_id: uuid.UUID | None = None,
        date_from: datetime | None = None,
        date_to: datetime | None = None,
        visible_to_user_id: int | None = None,
    ) -> PaginatedAppointments:
        """List appointments with optional filters.

        ``visible_to_user_id`` restricts the page to the appointments that user
        is booked on (see :meth:`booked_for_user_predicate`). Callers pass it for
        anyone below the dispatch tier; the remaining filters narrow that set
        further, never widen it.
        """
        query = (
            select(Appointment)
            .options(selectinload(Appointment.contact))
            .where(Appointment.workspace_id == workspace_id)
        )

        if visible_to_user_id is not None:
            query = query.where(self.booked_for_user_predicate(workspace_id, visible_to_user_id))
        if status_filter:
            query = query.where(Appointment.status == status_filter)
        if contact_id is not None:
            query = query.where(Appointment.contact_id == contact_id)
        if agent_id is not None:
            query = query.where(Appointment.agent_id == uuid.UUID(agent_id))
        if business_location_id is not None:
            query = query.where(Appointment.business_location_id == business_location_id)
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
        *,
        booked_for_user_id: int | None = None,
    ) -> Appointment:
        """Create an appointment and optionally tag a booking-enabled user.

        Restricted callers pass ``booked_for_user_id`` and are forced onto their
        own active booking resource. Dispatch-tier callers may choose an active
        login-backed staff row from the workspace scheduling roster.
        """
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
        if appointment_in.agent_id:
            agent_result = await self.db.execute(
                select(Agent).where(
                    Agent.id == uuid.UUID(appointment_in.agent_id),
                    Agent.workspace_id == workspace_id,
                )
            )
            if agent_result.scalar_one_or_none() is None:
                log.warning("agent_not_found")
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="Agent not found",
                )

        assigned_staff: BookableStaff | None = None
        if booked_for_user_id is not None:
            assigned_staff = await self._active_staff_for_user(workspace_id, booked_for_user_id)
            if assigned_staff is None:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail=(
                        "Your booking calendar is not enabled. Ask an admin to enable "
                        "it in Settings > Team."
                    ),
                )
        elif appointment_in.bookable_staff_id is not None:
            assigned_staff = await self._get_assignable_staff(
                workspace_id, appointment_in.bookable_staff_id
            )

        appointment = Appointment(
            workspace_id=workspace_id,
            agent_id=uuid.UUID(appointment_in.agent_id) if appointment_in.agent_id else None,
            bookable_staff_id=assigned_staff.id if assigned_staff else None,
            **appointment_in.model_dump(exclude={"agent_id", "bookable_staff_id"}),
        )
        self.db.add(appointment)
        await self.db.commit()
        await self.db.refresh(appointment)

        log.info(
            "appointment_created",
            appointment_id=appointment.id,
            bookable_staff_id=str(assigned_staff.id) if assigned_staff else None,
        )

        # Re-read through the eager-loading path. ``AppointmentResponse``
        # serializes a nested contact summary, and the bare instance above
        # leaves ``contact`` to lazy-load *after* the request session has
        # committed, which raises ``MissingGreenlet`` and turns a successful
        # booking into a 500 (the row is written, so the operator sees a
        # failure for an appointment that actually exists).
        return await self.get_appointment(workspace_id, appointment.id)

    async def get_appointment(
        self,
        workspace_id: uuid.UUID,
        appointment_id: int,
        *,
        visible_to_user_id: int | None = None,
    ) -> Appointment:
        """Get an appointment by ID, raising 404 if not found.

        Eager-loads ``contact`` so ``AppointmentResponse`` can serialize the
        nested contact summary without triggering an async lazy-load (which
        raises ``MissingGreenlet``) after the request session has committed.

        ``visible_to_user_id`` applies the same scope as the list, so a deep link
        to somebody else's appointment 404s instead of routing around it.
        """
        criteria: list[ColumnElement[bool]] = []
        if visible_to_user_id is not None:
            criteria.append(self.booked_for_user_predicate(workspace_id, visible_to_user_id))
        result = await self.db.execute(
            select(Appointment)
            .options(
                selectinload(Appointment.contact),
                selectinload(Appointment.bookable_staff),
            )
            .where(
                Appointment.id == appointment_id,
                Appointment.workspace_id == workspace_id,
                *criteria,
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
        *,
        visible_to_user_id: int | None = None,
    ) -> Appointment:
        """Update an appointment and move its external event when reassigned."""
        appointment = await self.get_appointment(
            workspace_id,
            appointment_id,
            visible_to_user_id=visible_to_user_id,
        )

        contact = appointment.contact
        previous_status = appointment.status
        had_google_event = appointment.google_calendar_event_id is not None
        previous_scheduled_at = appointment.scheduled_at
        previous_duration = appointment.duration_minutes
        update_data = appointment_in.model_dump(exclude_unset=True)

        # A branch assignment must belong to this workspace, so an appointment
        # can't be linked to another tenant's business location.
        business_location_id = update_data.get("business_location_id")
        if business_location_id is not None:
            await assert_workspace_owned(
                self.db,
                BusinessLocation,
                business_location_id,
                workspace_id,
                detail="Business location not found",
            )

        assigned_staff, assignment_changed = await self._prepare_staff_reassignment(
            appointment, workspace_id, update_data
        )

        for field, value in update_data.items():
            setattr(appointment, field, value)

        if (
            appointment.status == AppointmentStatus.CANCELLED
            and previous_status != appointment.status
        ):
            await delete_external_events(
                self.db,
                appointment=appointment,
                log=self.log,
            )
            if appointment.sync_status != "failed":
                appointment.sync_status = "cancelled"
                appointment.sync_error = None
                appointment.last_synced_at = datetime.now(UTC)

        # An operator marking attendance must leave the contact in exactly the
        # state the scheduling lifecycle expects: the lifecycle tag,
        # ``last_appointment_status``, and ``noshow_count``. Without this an
        # in-app no-show is invisible to the ``no_show`` automation trigger and
        # to ``noshow_reengagement_worker``.
        if appointment.status != previous_status:
            await record_attendance_outcome(self.db, appointment, previous_status=previous_status)

        schedule_changed = (
            appointment.scheduled_at != previous_scheduled_at
            or appointment.duration_minutes != previous_duration
        )
        if schedule_changed and appointment.status != AppointmentStatus.CANCELLED:
            workspace = await self.db.get(Workspace, appointment.workspace_id)
            await update_external_events(
                self.db,
                appointment=appointment,
                workspace=workspace,
                log=self.log,
            )

        await self.db.commit()
        await self.db.refresh(appointment)

        if (
            assignment_changed
            and had_google_event
            and assigned_staff is not None
            and appointment.status != AppointmentStatus.CANCELLED
        ):
            await self._sync_assigned_external_events(
                appointment, contact=contact, staff=assigned_staff
            )

        self.log.info(
            "appointment_updated",
            workspace_id=str(workspace_id),
            appointment_id=appointment_id,
            status=appointment.status,
            bookable_staff_id=(
                str(appointment.bookable_staff_id)
                if appointment.bookable_staff_id is not None
                else None
            ),
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
        *,
        visible_to_user_id: int | None = None,
    ) -> None:
        """Delete an appointment within the caller's visibility scope."""
        appointment = await self.get_appointment(
            workspace_id,
            appointment_id,
            visible_to_user_id=visible_to_user_id,
        )
        await delete_external_events(self.db, appointment=appointment, log=self.log)
        await self.db.delete(appointment)
        await self.db.commit()
        self.log.info(
            "appointment_deleted",
            workspace_id=str(workspace_id),
            appointment_id=appointment_id,
        )

    async def get_stats(
        self,
        workspace_id: uuid.UUID,
        *,
        visible_to_user_id: int | None = None,
    ) -> AppointmentStatsResponse:
        """Return show-up analytics within an optional assignee scope."""
        scope = (
            self.booked_for_user_predicate(workspace_id, visible_to_user_id)
            if visible_to_user_id is not None
            else None
        )
        overall_query = select(
            func.count(Appointment.id).label("total"),
            func.count(case((Appointment.status == "scheduled", 1))).label("scheduled"),
            func.count(case((Appointment.status == "completed", 1))).label("completed"),
            func.count(case((Appointment.status == "no_show", 1))).label("no_show"),
            func.count(case((Appointment.status == "cancelled", 1))).label("cancelled"),
        ).where(Appointment.workspace_id == workspace_id)
        if scope is not None:
            overall_query = overall_query.where(scope)
        overall_result = await self.db.execute(overall_query)
        row = overall_result.one()
        overall = AppointmentOverallStats(
            total=row.total,
            scheduled=row.scheduled,
            completed=row.completed,
            no_show=row.no_show,
            cancelled=row.cancelled,
            show_up_rate=_calc_show_up_rate(row.completed, row.no_show),
        )

        agent_query = (
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
        if scope is not None:
            agent_query = agent_query.where(scope)
        agent_rows_result = await self.db.execute(agent_query)
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

        campaign_query = (
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
        if scope is not None:
            campaign_query = campaign_query.where(scope)
        campaign_rows_result = await self.db.execute(campaign_query)
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
        *,
        visible_to_user_id: int | None = None,
    ) -> dict[str, Any]:
        """Send an SMS reminder for an appointment visible to the caller."""
        from app.services.calendar import reminder_service

        appointment = await self.get_appointment(
            workspace_id,
            appointment_id,
            visible_to_user_id=visible_to_user_id,
        )

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
