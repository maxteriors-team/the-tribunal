"""Workspace-scoped service for field-service jobs (work orders).

Mirrors :mod:`app.services.field_service`: every read and write is tenant-scoped
through :mod:`app.db.scope`, and cross-entity references (contact, service
location, crew, technicians) are validated to belong to the same workspace so a
caller cannot bind a job to another tenant's rows.

Job ``status`` is derived/maintained here in one place \u2014 on create, update, and
schedule \u2014 rather than being set ad hoc by callers, so it never drifts out of
sync with the time window.

A job response is *self-contained for the field*: the site address, the
customer's name and phone, and the scope of work are embedded, because the field
tier holds ``jobs:read`` only and is denied the contact/service-location
endpoints it would otherwise need to resolve them. Everything embedded is
price-free (see :class:`app.schemas.job.JobLineItemSummary`). The relations that
feeds are eager-loaded and line items are fetched one query per *page* rather
than one per job, so widening the payload did not add an N+1.
"""

from __future__ import annotations

import uuid
from collections import defaultdict
from collections.abc import Sequence
from datetime import datetime
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy import delete, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.db.scope import (
    assert_workspace_owned,
    select_workspace_owned,
)
from app.models.contact import Contact
from app.models.field_service import (
    Crew,
    Job,
    JobAssignment,
    JobStatus,
    ServiceLocation,
    Technician,
)
from app.models.invoice import Invoice, InvoiceLineItem
from app.schemas.job import (
    JobCustomerSummary,
    JobLineItemSummary,
    JobResponse,
    TechnicianSummary,
)
from app.services.automations.events import (
    EVENT_JOB_COMPLETED,
    EVENT_JOB_SCHEDULED,
    emit_automation_event,
)
from app.services.field_service.neighbor_outreach import NeighborOutreachService

# Job lifecycle states that drive an automation event when first entered.
_STATUS_EVENTS: dict[JobStatus, str] = {
    JobStatus.SCHEDULED: EVENT_JOB_SCHEDULED,
    JobStatus.COMPLETED: EVENT_JOB_COMPLETED,
}

# Relations every job response embeds. Eager-loaded on every read path so
# serialization never lazy-loads (which would raise under asyncio) and never
# degrades into a per-row query.
_LOAD_OPTIONS = (
    selectinload(Job.technicians),
    selectinload(Job.contact),
    selectinload(Job.service_location),
)


class JobService:
    """Workspace-scoped CRUD, scheduling, and assignment for jobs."""

    def __init__(self, db: AsyncSession):
        self.db = db

    # ------------------------------------------------------------------ #
    # Reference validation (tenant-safe)
    # ------------------------------------------------------------------ #
    async def _assert_contact(self, contact_id: int, workspace_id: uuid.UUID) -> None:
        await assert_workspace_owned(
            self.db, Contact, contact_id, workspace_id, detail="Contact not found"
        )

    async def _assert_location(self, location_id: uuid.UUID, workspace_id: uuid.UUID) -> None:
        await assert_workspace_owned(
            self.db,
            ServiceLocation,
            location_id,
            workspace_id,
            detail="Service location not found",
        )

    async def _assert_crew(self, crew_id: uuid.UUID, workspace_id: uuid.UUID) -> None:
        await assert_workspace_owned(self.db, Crew, crew_id, workspace_id, detail="Crew not found")

    async def _assert_invoice(self, invoice_id: uuid.UUID, workspace_id: uuid.UUID) -> None:
        await assert_workspace_owned(
            self.db, Invoice, invoice_id, workspace_id, detail="Invoice not found"
        )

    async def _assert_technicians(
        self, technician_ids: Sequence[uuid.UUID], workspace_id: uuid.UUID
    ) -> None:
        """Validate every technician id belongs to the workspace (tenant-safe 404)."""
        unique_ids = set(technician_ids)
        for technician_id in unique_ids:
            await assert_workspace_owned(
                self.db,
                Technician,
                technician_id,
                workspace_id,
                detail="Technician not found",
            )

    async def _validate_refs(self, workspace_id: uuid.UUID, data: dict[str, Any]) -> None:
        """Validate optional location/crew references when present."""
        location_id = data.get("service_location_id")
        if location_id is not None:
            await self._assert_location(location_id, workspace_id)
        crew_id = data.get("crew_id")
        if crew_id is not None:
            await self._assert_crew(crew_id, workspace_id)
        invoice_id = data.get("invoice_id")
        if invoice_id is not None:
            await self._assert_invoice(invoice_id, workspace_id)

    # ------------------------------------------------------------------ #
    # Response building
    # ------------------------------------------------------------------ #
    @staticmethod
    def _to_response(job: Job, line_items: Sequence[InvoiceLineItem] = ()) -> JobResponse:
        """Build a response from a job with :data:`_LOAD_OPTIONS` relations loaded.

        ``service_location`` is populated by ``model_validate`` straight off the
        eager-loaded relation; the customer is mapped by hand so only name and
        phone cross the boundary (see :class:`JobCustomerSummary`).
        """
        response = JobResponse.model_validate(job)
        response.technicians = [
            TechnicianSummary.model_validate(tech)
            for tech in sorted(job.technicians, key=lambda t: t.name)
        ]
        contact = job.contact
        if contact is not None:
            response.customer = JobCustomerSummary(
                id=contact.id,
                name=contact.full_name,
                phone_number=contact.phone_number,
            )
        response.line_items = [JobLineItemSummary.model_validate(item) for item in line_items]
        return response

    async def _line_items_by_invoice(
        self, workspace_id: uuid.UUID, invoice_ids: set[uuid.UUID]
    ) -> dict[uuid.UUID, list[InvoiceLineItem]]:
        """Scope-of-work lines for the given invoices, in one query.

        One statement for a whole page of jobs rather than one per job, so the
        calendar's query count stays flat as the day fills up. Joined through
        :class:`Invoice` and filtered on ``workspace_id`` so a stale or tampered
        ``job.invoice_id`` can never reach another tenant's lines.
        """
        if not invoice_ids:
            return {}
        rows = (
            (
                await self.db.execute(
                    select(InvoiceLineItem)
                    .join(Invoice, Invoice.id == InvoiceLineItem.invoice_id)
                    .where(
                        Invoice.workspace_id == workspace_id,
                        InvoiceLineItem.invoice_id.in_(invoice_ids),
                    )
                    .order_by(InvoiceLineItem.invoice_id, InvoiceLineItem.created_at)
                )
            )
            .scalars()
            .all()
        )
        grouped: dict[uuid.UUID, list[InvoiceLineItem]] = defaultdict(list)
        for row in rows:
            grouped[row.invoice_id].append(row)
        return grouped

    async def _to_responses(
        self, jobs: Sequence[Job], workspace_id: uuid.UUID
    ) -> list[JobResponse]:
        """Serialize a page of jobs, batching their scope-of-work lookup."""
        grouped = await self._line_items_by_invoice(
            workspace_id, {job.invoice_id for job in jobs if job.invoice_id is not None}
        )
        return [
            self._to_response(job, grouped.get(job.invoice_id, ()) if job.invoice_id else ())
            for job in jobs
        ]

    async def _one_response(self, job: Job, workspace_id: uuid.UUID) -> JobResponse:
        """Serialize a single job (same embedding rules as a page)."""
        return (await self._to_responses([job], workspace_id))[0]

    async def _load(self, job_id: uuid.UUID, workspace_id: uuid.UUID) -> Job:
        """Fetch a workspace-owned job with response relations loaded, or 404."""
        return await assert_workspace_owned(
            self.db,
            Job,
            job_id,
            workspace_id,
            detail="Job not found",
            options=list(_LOAD_OPTIONS),
        )

    # ------------------------------------------------------------------ #
    # Queries
    # ------------------------------------------------------------------ #
    async def list(
        self,
        workspace_id: uuid.UUID,
        *,
        status: JobStatus | None = None,
        crew_id: uuid.UUID | None = None,
        technician_id: uuid.UUID | None = None,
        date_from: datetime | None = None,
        date_to: datetime | None = None,
    ) -> dict[str, Any]:
        """List jobs for the board/calendar, with optional filters."""
        criteria: list[Any] = []
        if status is not None:
            criteria.append(Job.status == status)
        if crew_id is not None:
            criteria.append(Job.crew_id == crew_id)
        if date_from is not None:
            criteria.append(Job.scheduled_start >= date_from)
        if date_to is not None:
            criteria.append(Job.scheduled_start <= date_to)
        if technician_id is not None:
            criteria.append(
                Job.id.in_(
                    select(JobAssignment.job_id).where(JobAssignment.technician_id == technician_id)
                )
            )

        query = select_workspace_owned(
            Job, workspace_id, *criteria, options=list(_LOAD_OPTIONS)
        ).order_by(Job.scheduled_start.is_(None), Job.scheduled_start, Job.created_at.desc())
        rows = (await self.db.execute(query)).scalars().all()
        items = await self._to_responses(rows, workspace_id)
        return {"items": items, "total": len(items)}

    async def get(self, job_id: uuid.UUID, workspace_id: uuid.UUID) -> JobResponse:
        job = await self._load(job_id, workspace_id)
        return await self._one_response(job, workspace_id)

    async def list_for_user(
        self,
        workspace_id: uuid.UUID,
        user_id: int,
        *,
        date_from: datetime | None = None,
        date_to: datetime | None = None,
    ) -> dict[str, Any]:
        """Jobs visible to ``user_id`` on *their* calendar.

        Resolves the user to their technician row(s) in this workspace, then
        returns jobs either tagged directly to those technicians or assigned to a
        crew they belong to. Returns an empty list (not an error) when the user
        has no technician record \u2014 a login simply isn't a field worker yet.
        """
        tech_rows = (
            await self.db.execute(
                select(Technician.id, Technician.crew_id).where(
                    Technician.workspace_id == workspace_id,
                    Technician.user_id == user_id,
                )
            )
        ).all()
        if not tech_rows:
            return {"items": [], "total": 0}

        technician_ids = [row[0] for row in tech_rows]
        crew_ids = [row[1] for row in tech_rows if row[1] is not None]

        visibility = [
            Job.id.in_(
                select(JobAssignment.job_id).where(JobAssignment.technician_id.in_(technician_ids))
            )
        ]
        if crew_ids:
            visibility.append(Job.crew_id.in_(crew_ids))

        # A job is on the worker's calendar if it's tagged to them OR routed to
        # one of their crews.
        criteria: list[Any] = [or_(*visibility)]
        if date_from is not None:
            criteria.append(Job.scheduled_start >= date_from)
        if date_to is not None:
            criteria.append(Job.scheduled_start <= date_to)

        query = select_workspace_owned(
            Job, workspace_id, *criteria, options=list(_LOAD_OPTIONS)
        ).order_by(Job.scheduled_start.is_(None), Job.scheduled_start, Job.created_at.desc())
        rows = (await self.db.execute(query)).scalars().all()
        items = await self._to_responses(rows, workspace_id)
        return {"items": items, "total": len(items)}

    # ------------------------------------------------------------------ #
    # Automation events
    # ------------------------------------------------------------------ #
    async def _emit_status_event(self, job: Job, prior_status: JobStatus | str | None) -> None:
        """React to ``job`` first entering scheduled/completed.

        No-op when the status did not change. Shares the caller's transaction (the
        route's transactional session, or the converting quote's), so the effects
        are durable iff the status change commits. ``emit_automation_event`` itself
        no-ops when no automation listens for the trigger.

        Completion additionally kicks off neighbour-outreach generation, because a
        finished job is the moment the surrounding street is warmest. That call
        never sends anything, is workspace-config gated, and swallows its own
        errors inside a ``SAVEPOINT`` — a marketing list must not be able to fail a
        work-order update.
        """
        new_status = JobStatus(job.status)
        if prior_status is not None and JobStatus(prior_status) == new_status:
            return

        if new_status == JobStatus.COMPLETED:
            await NeighborOutreachService(self.db).maybe_generate_on_completion(job)

        event_type = _STATUS_EVENTS.get(new_status)
        if event_type is None:
            return
        await emit_automation_event(
            self.db,
            workspace_id=job.workspace_id,
            event_type=event_type,
            contact_id=job.contact_id,
            payload={
                "job_id": str(job.id),
                "status": str(new_status),
                "title": job.title,
                "scheduled_start": (
                    job.scheduled_start.isoformat() if job.scheduled_start else None
                ),
            },
        )

    # ------------------------------------------------------------------ #
    # Mutations
    # ------------------------------------------------------------------ #
    @staticmethod
    def _status_for_window(start: datetime | None, end: datetime | None) -> JobStatus:
        """Derive the queued/scheduled status from the presence of a window."""
        if start is not None and end is not None:
            return JobStatus.SCHEDULED
        return JobStatus.UNSCHEDULED

    async def create(self, workspace_id: uuid.UUID, data: dict[str, Any]) -> JobResponse:
        await self._assert_contact(data["contact_id"], workspace_id)
        await self._validate_refs(workspace_id, data)

        technician_ids: Sequence[uuid.UUID] = data.pop("technician_ids", []) or []
        if technician_ids:
            await self._assert_technicians(technician_ids, workspace_id)

        job = Job(
            workspace_id=workspace_id,
            status=self._status_for_window(data.get("scheduled_start"), data.get("scheduled_end")),
            **data,
        )
        self.db.add(job)
        await self.db.flush()

        for technician_id in dict.fromkeys(technician_ids):
            self.db.add(JobAssignment(job_id=job.id, technician_id=technician_id))
        await self.db.flush()

        # A job created already inside a time window lands ``scheduled``.
        await self._emit_status_event(job, prior_status=None)
        return await self._one_response(await self._load(job.id, workspace_id), workspace_id)

    async def update(
        self, job_id: uuid.UUID, workspace_id: uuid.UUID, data: dict[str, Any]
    ) -> JobResponse:
        job = await self._load(job_id, workspace_id)
        prior_status = job.status
        await self._validate_refs(workspace_id, data)

        for key, value in data.items():
            setattr(job, key, value)

        # Guard window ordering against the merged row state — a partial PATCH may
        # set only one bound against an existing one, which the schema can't see.
        if (
            job.scheduled_start is not None
            and job.scheduled_end is not None
            and job.scheduled_end <= job.scheduled_start
        ):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="scheduled_end must be after scheduled_start",
            )

        # Recompute queued/scheduled status when the window changes, unless the
        # caller explicitly advanced the lifecycle (in_progress/completed/etc.).
        window_touched = "scheduled_start" in data or "scheduled_end" in data
        if window_touched and "status" not in data:
            job.status = self._status_for_window(job.scheduled_start, job.scheduled_end)

        await self.db.flush()
        await self._emit_status_event(job, prior_status)
        return await self._one_response(await self._load(job.id, workspace_id), workspace_id)

    async def schedule(
        self,
        job_id: uuid.UUID,
        workspace_id: uuid.UUID,
        start: datetime,
        end: datetime,
    ) -> JobResponse:
        """Set the time window; flip ``unscheduled`` -> ``scheduled``."""
        job = await self._load(job_id, workspace_id)
        prior_status = job.status
        job.scheduled_start = start
        job.scheduled_end = end
        if job.status == JobStatus.UNSCHEDULED:
            job.status = JobStatus.SCHEDULED
        await self.db.flush()
        await self._emit_status_event(job, prior_status)
        return await self._one_response(await self._load(job.id, workspace_id), workspace_id)

    async def assign_technicians(
        self, job_id: uuid.UUID, workspace_id: uuid.UUID, technician_ids: Sequence[uuid.UUID]
    ) -> JobResponse:
        """Tag technicians onto a job. Idempotent: existing tags are skipped."""
        job = await self._load(job_id, workspace_id)
        await self._assert_technicians(technician_ids, workspace_id)

        existing = {
            row[0]
            for row in (
                await self.db.execute(
                    select(JobAssignment.technician_id).where(JobAssignment.job_id == job.id)
                )
            ).all()
        }
        for technician_id in dict.fromkeys(technician_ids):
            if technician_id not in existing:
                self.db.add(JobAssignment(job_id=job.id, technician_id=technician_id))
        await self.db.flush()
        # The viewonly ``technicians`` collection was loaded by ``_load``; expire
        # it so the reload below reflects the new tags rather than the cache.
        self.db.expire(job, ["technicians"])
        return await self._one_response(await self._load(job.id, workspace_id), workspace_id)

    async def unassign_technician(
        self, job_id: uuid.UUID, workspace_id: uuid.UUID, technician_id: uuid.UUID
    ) -> JobResponse:
        """Untag a technician from a job. No-op if not currently tagged."""
        job = await self._load(job_id, workspace_id)
        await self.db.execute(
            delete(JobAssignment).where(
                JobAssignment.job_id == job.id,
                JobAssignment.technician_id == technician_id,
            )
        )
        await self.db.flush()
        # Core DELETE bypasses the ORM; expire the cached collection so the
        # reload reflects the removal.
        self.db.expire(job, ["technicians"])
        return await self._one_response(await self._load(job.id, workspace_id), workspace_id)

    async def delete(self, job_id: uuid.UUID, workspace_id: uuid.UUID) -> None:
        job = await assert_workspace_owned(
            self.db, Job, job_id, workspace_id, detail="Job not found"
        )
        await self.db.delete(job)
