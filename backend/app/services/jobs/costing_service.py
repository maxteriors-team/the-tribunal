"""Job time-tracking, expenses, and profitability.

Workspace-scoped like :class:`app.services.jobs.job_service.JobService`: every
job, time entry, and expense is validated to belong to the caller's workspace
through :mod:`app.db.scope`, so a caller can never read or mutate another
tenant's rows. Money math uses ``float`` rounded to two decimals to match the
invoice/quote services.

**Cost visibility is a parameter of every time-entry read.** Callers pass
``include_costs`` (the route derives it from ``billing:read``); when false the
``rate``/``labor_cost`` fields are served as 0 and a client-supplied rate is
discarded on write. The field tier therefore keeps its operational view of a job
(is a timer running, how many hours) with no pricing attached. Expenses are
gated at the route instead — an expense row is nothing *but* money, so there is
no price-free projection worth serving (see :mod:`app.api.v1.jobs`).
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Literal, cast

import structlog
from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.scope import assert_workspace_owned, select_workspace_owned
from app.models.contact import Contact
from app.models.field_service import Job, JobStatus, Technician
from app.models.invoice import Invoice
from app.models.job_costing import JobExpense, TimeEntry
from app.models.user import User
from app.schemas.job_costing import (
    ClockInRequest,
    ContactJobTimeEntryResponse,
    ContactJobTimeSummaryResponse,
    JobExpenseCreate,
    JobExpenseResponse,
    JobProfitability,
    TimeEntryCreate,
    TimeEntryResponse,
)
from app.services.exceptions import ConflictError
from app.services.inventory.cogs_service import COGSService

logger = structlog.get_logger()


def _duration_hours(started_at: datetime, ended_at: datetime | None) -> float:
    """Hours between start and end, or 0 while the clock is still running."""
    if ended_at is None:
        return 0.0
    return round((ended_at - started_at).total_seconds() / 3600.0, 4)


class JobCostingService:
    """Time entries, expenses, and per-job profitability."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self.log = logger.bind(component="job_costing_service")

    # ------------------------------------------------------------------ #
    # Reference validation (tenant-safe)
    # ------------------------------------------------------------------ #
    async def _assert_job(
        self,
        job_id: uuid.UUID,
        workspace_id: uuid.UUID,
        *,
        visible_to_user_id: int | None = None,
        for_update: bool = False,
    ) -> Job:
        filters = [Job.id == job_id, Job.workspace_id == workspace_id]
        if visible_to_user_id is not None:
            # Local import avoids the package-level JobService/JobCostingService cycle.
            from app.services.jobs.job_service import JobService

            filters.append(
                await JobService(self.db).assigned_job_predicate(workspace_id, visible_to_user_id)
            )
        statement = select(Job).where(*filters)
        if for_update:
            # Timer transitions lock one job row. This serializes starts for the
            # same job and lets the partial unique index remain the final guard.
            statement = statement.with_for_update()
        job = (await self.db.execute(statement)).scalar_one_or_none()
        if job is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Job not found")
        return job

    async def _assert_technician(self, technician_id: uuid.UUID, workspace_id: uuid.UUID) -> None:
        await assert_workspace_owned(
            self.db, Technician, technician_id, workspace_id, detail="Technician not found"
        )

    async def _technician_for_user(self, workspace_id: uuid.UUID, user_id: int) -> uuid.UUID | None:
        return (
            (
                await self.db.execute(
                    select(Technician.id)
                    .where(
                        Technician.workspace_id == workspace_id,
                        Technician.user_id == user_id,
                        Technician.is_active.is_(True),
                    )
                    .order_by(Technician.id)
                )
            )
            .scalars()
            .first()
        )

    @staticmethod
    def _rate_for(requested: float, *, include_costs: bool) -> float:
        """The rate to persist: a caller who cannot read money cannot set it."""
        return requested if include_costs else 0.0

    # ------------------------------------------------------------------ #
    # Response building
    # ------------------------------------------------------------------ #
    @staticmethod
    def _time_entry_response(
        entry: TimeEntry,
        *,
        include_costs: bool = True,
        viewer_user_id: int | None = None,
    ) -> TimeEntryResponse:
        """Serialize time while redacting rates from callers without billing access."""
        hours = _duration_hours(entry.started_at, entry.ended_at)
        rate = float(entry.rate or 0) if include_costs else 0.0
        return TimeEntryResponse(
            id=entry.id,
            job_id=entry.job_id,
            technician_id=entry.technician_id,
            started_at=entry.started_at,
            ended_at=entry.ended_at,
            stop_reason=cast(Literal["paused", "ended", "manual"] | None, entry.stop_reason),
            is_mine=viewer_user_id is not None and entry.created_by_id == viewer_user_id,
            rate=rate,
            note=entry.note,
            duration_hours=hours,
            labor_cost=round(hours * rate, 2),
            created_at=entry.created_at,
            updated_at=entry.updated_at,
        )

    # ------------------------------------------------------------------ #
    # Time entries
    # ------------------------------------------------------------------ #
    async def list_time_entries(
        self,
        job_id: uuid.UUID,
        workspace_id: uuid.UUID,
        *,
        include_costs: bool = True,
        viewer_user_id: int | None = None,
        visible_to_user_id: int | None = None,
    ) -> list[TimeEntryResponse]:
        await self._assert_job(job_id, workspace_id, visible_to_user_id=visible_to_user_id)
        rows = (
            (
                await self.db.execute(
                    select_workspace_owned(
                        TimeEntry, workspace_id, TimeEntry.job_id == job_id
                    ).order_by(TimeEntry.started_at.desc())
                )
            )
            .scalars()
            .all()
        )
        return [
            self._time_entry_response(
                row, include_costs=include_costs, viewer_user_id=viewer_user_id
            )
            for row in rows
        ]

    async def _latest_timer_entry(
        self, job_id: uuid.UUID, workspace_id: uuid.UUID, created_by_id: int
    ) -> TimeEntry | None:
        """Return this user's latest non-manual timer interval for the job."""
        return (
            (
                await self.db.execute(
                    select_workspace_owned(
                        TimeEntry,
                        workspace_id,
                        TimeEntry.job_id == job_id,
                        TimeEntry.created_by_id == created_by_id,
                        (TimeEntry.stop_reason.is_(None) | (TimeEntry.stop_reason != "manual")),
                    ).order_by(TimeEntry.started_at.desc())
                )
            )
            .scalars()
            .first()
        )

    async def clock_in(
        self,
        job_id: uuid.UUID,
        workspace_id: uuid.UUID,
        payload: ClockInRequest,
        *,
        created_by_id: int,
        include_costs: bool = True,
        visible_to_user_id: int | None = None,
    ) -> TimeEntryResponse:
        """Start or resume this user's timer for an assigned job."""
        job = await self._assert_job(
            job_id,
            workspace_id,
            visible_to_user_id=visible_to_user_id,
            for_update=True,
        )
        if job.status in {JobStatus.COMPLETED, JobStatus.CANCELLED}:
            raise ConflictError("Time cannot be added to a completed or cancelled job")

        technician_id = payload.technician_id
        if technician_id is not None:
            await self._assert_technician(technician_id, workspace_id)
        else:
            technician_id = await self._technician_for_user(workspace_id, created_by_id)

        latest = await self._latest_timer_entry(job_id, workspace_id, created_by_id)
        if latest is not None and latest.ended_at is None:
            raise ConflictError("Your timer is already running on this job")
        # An ended interval is final, but the job may need a later return visit.
        # Starting again opens a fresh interval; only a paused interval is resumed.
        now = datetime.now(UTC)
        entry = TimeEntry(
            workspace_id=workspace_id,
            job_id=job_id,
            technician_id=technician_id,
            started_at=now,
            ended_at=None,
            stop_reason=None,
            rate=self._rate_for(payload.rate, include_costs=include_costs),
            note=payload.note,
            created_by_id=created_by_id,
        )
        self.db.add(entry)
        await self.db.flush()
        await self.db.refresh(entry)
        self.log.info("job_timer_started", job_id=str(job_id), entry_id=str(entry.id))
        return self._time_entry_response(
            entry, include_costs=include_costs, viewer_user_id=created_by_id
        )

    async def pause_timer(
        self,
        job_id: uuid.UUID,
        workspace_id: uuid.UUID,
        *,
        created_by_id: int,
        include_costs: bool = True,
        visible_to_user_id: int | None = None,
    ) -> TimeEntryResponse:
        """Pause this user's running timer, preserving the completed interval."""
        await self._assert_job(
            job_id,
            workspace_id,
            visible_to_user_id=visible_to_user_id,
            for_update=True,
        )
        entry = await self._latest_timer_entry(job_id, workspace_id, created_by_id)
        if entry is None:
            raise ConflictError("Your timer has not been started on this job")
        if entry.stop_reason == "ended":
            raise ConflictError("Your timer for this job has ended")
        if entry.ended_at is not None:
            if entry.stop_reason == "paused":
                return self._time_entry_response(
                    entry, include_costs=include_costs, viewer_user_id=created_by_id
                )
            raise ConflictError("Your timer is not running on this job")

        entry.ended_at = datetime.now(UTC)
        entry.stop_reason = "paused"
        await self.db.flush()
        await self.db.refresh(entry)
        self.log.info("job_timer_paused", job_id=str(job_id), entry_id=str(entry.id))
        return self._time_entry_response(
            entry, include_costs=include_costs, viewer_user_id=created_by_id
        )

    async def end_timer(
        self,
        job_id: uuid.UUID,
        workspace_id: uuid.UUID,
        *,
        created_by_id: int,
        include_costs: bool = True,
        visible_to_user_id: int | None = None,
    ) -> TimeEntryResponse:
        """End this user's timer after a running or paused interval."""
        await self._assert_job(
            job_id,
            workspace_id,
            visible_to_user_id=visible_to_user_id,
            for_update=True,
        )
        entry = await self._latest_timer_entry(job_id, workspace_id, created_by_id)
        if entry is None:
            raise ConflictError("Your timer has not been started on this job")
        if entry.stop_reason == "ended":
            return self._time_entry_response(
                entry, include_costs=include_costs, viewer_user_id=created_by_id
            )
        if entry.ended_at is None:
            entry.ended_at = datetime.now(UTC)
        elif entry.stop_reason != "paused":
            raise ConflictError("Your timer is not running or paused on this job")
        entry.stop_reason = "ended"
        await self.db.flush()
        await self.db.refresh(entry)
        self.log.info("job_timer_ended", job_id=str(job_id), entry_id=str(entry.id))
        return self._time_entry_response(
            entry, include_costs=include_costs, viewer_user_id=created_by_id
        )

    async def clock_out(
        self,
        job_id: uuid.UUID,
        workspace_id: uuid.UUID,
        *,
        created_by_id: int,
        include_costs: bool = True,
        visible_to_user_id: int | None = None,
    ) -> TimeEntryResponse:
        """Backward-compatible alias: clocking out pauses the current user's timer."""
        return await self.pause_timer(
            job_id,
            workspace_id,
            created_by_id=created_by_id,
            include_costs=include_costs,
            visible_to_user_id=visible_to_user_id,
        )

    async def add_time_entry(
        self,
        job_id: uuid.UUID,
        workspace_id: uuid.UUID,
        payload: TimeEntryCreate,
        *,
        created_by_id: int | None = None,
        include_costs: bool = True,
        visible_to_user_id: int | None = None,
    ) -> TimeEntryResponse:
        """Log a completed manual entry from an explicit start and end."""
        await self._assert_job(job_id, workspace_id, visible_to_user_id=visible_to_user_id)
        technician_id = payload.technician_id
        if technician_id is not None:
            await self._assert_technician(technician_id, workspace_id)
        elif created_by_id is not None:
            technician_id = await self._technician_for_user(workspace_id, created_by_id)
        if payload.ended_at <= payload.started_at:
            raise ConflictError("ended_at must be after started_at")

        entry = TimeEntry(
            workspace_id=workspace_id,
            job_id=job_id,
            technician_id=technician_id,
            started_at=payload.started_at,
            ended_at=payload.ended_at,
            stop_reason="manual",
            rate=self._rate_for(payload.rate, include_costs=include_costs),
            note=payload.note,
            created_by_id=created_by_id,
        )
        self.db.add(entry)
        await self.db.flush()
        await self.db.refresh(entry)
        return self._time_entry_response(
            entry, include_costs=include_costs, viewer_user_id=created_by_id
        )

    async def delete_time_entry(
        self,
        job_id: uuid.UUID,
        workspace_id: uuid.UUID,
        entry_id: uuid.UUID,
        *,
        restrict_to_user_id: int | None = None,
        visible_to_user_id: int | None = None,
    ) -> None:
        """Delete a visible time entry, optionally restricted to its creator."""
        await self._assert_job(job_id, workspace_id, visible_to_user_id=visible_to_user_id)
        ownership = (
            (TimeEntry.created_by_id == restrict_to_user_id,)
            if restrict_to_user_id is not None
            else ()
        )
        entry = await assert_workspace_owned(
            self.db,
            TimeEntry,
            entry_id,
            workspace_id,
            TimeEntry.job_id == job_id,
            *ownership,
            detail="Time entry not found",
        )
        await self.db.delete(entry)
        await self.db.flush()

    async def get_contact_time_summary(
        self, contact_id: int, workspace_id: uuid.UUID, *, limit: int = 50
    ) -> ContactJobTimeSummaryResponse:
        """Return saved, price-free job time associated with one client profile."""
        await assert_workspace_owned(
            self.db, Contact, contact_id, workspace_id, detail="Contact not found"
        )
        job_filter = (
            Job.workspace_id == workspace_id,
            Job.contact_id == contact_id,
        )
        duration_seconds = func.extract("epoch", TimeEntry.ended_at - TimeEntry.started_at)
        entry_count, total_seconds = (
            await self.db.execute(
                select(
                    func.count(TimeEntry.id),
                    func.coalesce(func.sum(duration_seconds), 0),
                )
                .select_from(TimeEntry)
                .join(Job, Job.id == TimeEntry.job_id)
                .where(TimeEntry.workspace_id == workspace_id, *job_filter)
            )
        ).one()

        rows = (
            await self.db.execute(
                select(TimeEntry, Job.title, Technician.name, User.full_name)
                .join(Job, Job.id == TimeEntry.job_id)
                .outerjoin(Technician, Technician.id == TimeEntry.technician_id)
                .outerjoin(User, User.id == TimeEntry.created_by_id)
                .where(TimeEntry.workspace_id == workspace_id, *job_filter)
                .order_by(TimeEntry.started_at.desc())
                .limit(limit)
            )
        ).all()
        entries = [
            ContactJobTimeEntryResponse(
                id=entry.id,
                job_id=entry.job_id,
                job_title=job_title,
                technician_name=technician_name or creator_name,
                started_at=entry.started_at,
                ended_at=entry.ended_at,
                stop_reason=cast(Literal["paused", "ended", "manual"] | None, entry.stop_reason),
                duration_hours=_duration_hours(entry.started_at, entry.ended_at),
            )
            for entry, job_title, technician_name, creator_name in rows
        ]
        return ContactJobTimeSummaryResponse(
            total_hours=round(float(total_seconds or 0) / 3600.0, 4),
            entry_count=int(entry_count or 0),
            entries=entries,
        )

    # ------------------------------------------------------------------ #
    # Expenses
    # ------------------------------------------------------------------ #
    async def list_expenses(
        self,
        job_id: uuid.UUID,
        workspace_id: uuid.UUID,
        *,
        visible_to_user_id: int | None = None,
    ) -> list[JobExpenseResponse]:
        await self._assert_job(job_id, workspace_id, visible_to_user_id=visible_to_user_id)
        rows = (
            (
                await self.db.execute(
                    select_workspace_owned(
                        JobExpense, workspace_id, JobExpense.job_id == job_id
                    ).order_by(JobExpense.created_at.desc())
                )
            )
            .scalars()
            .all()
        )
        return [JobExpenseResponse.model_validate(row) for row in rows]

    async def add_expense(
        self,
        job_id: uuid.UUID,
        workspace_id: uuid.UUID,
        payload: JobExpenseCreate,
        *,
        created_by_id: int | None = None,
        visible_to_user_id: int | None = None,
    ) -> JobExpenseResponse:
        await self._assert_job(job_id, workspace_id, visible_to_user_id=visible_to_user_id)
        expense = JobExpense(
            workspace_id=workspace_id,
            job_id=job_id,
            description=payload.description,
            amount=payload.amount,
            category=payload.category,
            incurred_on=payload.incurred_on,
            note=payload.note,
            created_by_id=created_by_id,
        )
        self.db.add(expense)
        await self.db.flush()
        await self.db.refresh(expense)
        self.log.info("job_expense_added", job_id=str(job_id), expense_id=str(expense.id))
        return JobExpenseResponse.model_validate(expense)

    async def delete_expense(
        self,
        job_id: uuid.UUID,
        workspace_id: uuid.UUID,
        expense_id: uuid.UUID,
        *,
        restrict_to_user_id: int | None = None,
        visible_to_user_id: int | None = None,
    ) -> None:
        """Delete an expense, optionally only if ``restrict_to_user_id`` recorded it.

        A caller without ``billing:write`` may only delete their own (see
        :func:`app.core.permissions.job_expense_owner_scope`). The restriction is
        an extra filter on the lookup rather than a check after it, so another
        member's expense reads as "not found" and its existence is not disclosed
        — which matters here because the same tier cannot read the expense list
        at all.
        """
        await self._assert_job(job_id, workspace_id, visible_to_user_id=visible_to_user_id)
        ownership = (
            (JobExpense.created_by_id == restrict_to_user_id,)
            if restrict_to_user_id is not None
            else ()
        )
        expense = await assert_workspace_owned(
            self.db,
            JobExpense,
            expense_id,
            workspace_id,
            JobExpense.job_id == job_id,
            *ownership,
            detail="Expense not found",
        )
        await self.db.delete(expense)
        await self.db.flush()

    # ------------------------------------------------------------------ #
    # Profitability
    # ------------------------------------------------------------------ #
    async def get_profitability(
        self,
        job_id: uuid.UUID,
        workspace_id: uuid.UUID,
        *,
        visible_to_user_id: int | None = None,
    ) -> JobProfitability:
        """Revenue (linked invoice) minus labor, expenses, and materials."""
        job = await self._assert_job(job_id, workspace_id, visible_to_user_id=visible_to_user_id)

        revenue = 0.0
        currency = "USD"
        if job.invoice_id is not None:
            invoice = (
                await self.db.execute(
                    select(Invoice).where(
                        Invoice.id == job.invoice_id,
                        Invoice.workspace_id == workspace_id,
                    )
                )
            ).scalar_one_or_none()
            if invoice is not None:
                revenue = float(invoice.total or 0)
                currency = invoice.currency

        entries = (
            (
                await self.db.execute(
                    select_workspace_owned(TimeEntry, workspace_id, TimeEntry.job_id == job_id)
                )
            )
            .scalars()
            .all()
        )
        labor_cost = 0.0
        total_hours = 0.0
        open_timer = False
        for entry in entries:
            hours = _duration_hours(entry.started_at, entry.ended_at)
            total_hours += hours
            labor_cost += hours * float(entry.rate or 0)
            if entry.ended_at is None:
                open_timer = True

        expense_rows = (
            (
                await self.db.execute(
                    select(JobExpense.amount).where(
                        JobExpense.workspace_id == workspace_id,
                        JobExpense.job_id == job_id,
                    )
                )
            )
            .scalars()
            .all()
        )
        expense_cost = sum(float(amount or 0) for amount in expense_rows)

        # Materials come from the inventory ledger, never from a JobExpense, so
        # a workspace that tracks stock cannot count the same bucket twice.
        material_cost = (
            await COGSService(self.db).material_cost_by_job(workspace_id, [job_id])
        ).get(job_id, 0.0)

        labor_cost = round(labor_cost, 2)
        expense_cost = round(expense_cost, 2)
        material_cost = round(material_cost, 2)
        total_cost = round(labor_cost + expense_cost + material_cost, 2)
        profit = round(revenue - total_cost, 2)
        margin = round(profit / revenue, 4) if revenue else None

        return JobProfitability(
            job_id=job_id,
            currency=currency,
            revenue=round(revenue, 2),
            labor_cost=labor_cost,
            expense_cost=expense_cost,
            material_cost=material_cost,
            total_cost=total_cost,
            profit=profit,
            margin=margin,
            total_hours=round(total_hours, 2),
            open_timer=open_timer,
        )
