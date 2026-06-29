"""Job time-tracking, expenses, and profitability.

Workspace-scoped like :class:`app.services.jobs.job_service.JobService`: every
job, time entry, and expense is validated to belong to the caller's workspace
through :mod:`app.db.scope`, so a caller can never read or mutate another
tenant's rows. Money math uses ``float`` rounded to two decimals to match the
invoice/quote services.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.scope import assert_workspace_owned, select_workspace_owned
from app.models.field_service import Job, Technician
from app.models.invoice import Invoice
from app.models.job_costing import JobExpense, TimeEntry
from app.schemas.job_costing import (
    ClockInRequest,
    JobExpenseCreate,
    JobExpenseResponse,
    JobProfitability,
    TimeEntryCreate,
    TimeEntryResponse,
)
from app.services.exceptions import ConflictError

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
    async def _assert_job(self, job_id: uuid.UUID, workspace_id: uuid.UUID) -> Job:
        return await assert_workspace_owned(
            self.db, Job, job_id, workspace_id, detail="Job not found"
        )

    async def _assert_technician(self, technician_id: uuid.UUID, workspace_id: uuid.UUID) -> None:
        await assert_workspace_owned(
            self.db, Technician, technician_id, workspace_id, detail="Technician not found"
        )

    # ------------------------------------------------------------------ #
    # Response building
    # ------------------------------------------------------------------ #
    @staticmethod
    def _time_entry_response(entry: TimeEntry) -> TimeEntryResponse:
        hours = _duration_hours(entry.started_at, entry.ended_at)
        return TimeEntryResponse(
            id=entry.id,
            job_id=entry.job_id,
            technician_id=entry.technician_id,
            started_at=entry.started_at,
            ended_at=entry.ended_at,
            rate=float(entry.rate or 0),
            note=entry.note,
            duration_hours=hours,
            labor_cost=round(hours * float(entry.rate or 0), 2),
            created_at=entry.created_at,
            updated_at=entry.updated_at,
        )

    # ------------------------------------------------------------------ #
    # Time entries
    # ------------------------------------------------------------------ #
    async def list_time_entries(
        self, job_id: uuid.UUID, workspace_id: uuid.UUID
    ) -> list[TimeEntryResponse]:
        await self._assert_job(job_id, workspace_id)
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
        return [self._time_entry_response(row) for row in rows]

    async def _open_entry(self, job_id: uuid.UUID, workspace_id: uuid.UUID) -> TimeEntry | None:
        """Return the job's currently-running entry, if any."""
        return (
            (
                await self.db.execute(
                    select_workspace_owned(
                        TimeEntry,
                        workspace_id,
                        TimeEntry.job_id == job_id,
                        TimeEntry.ended_at.is_(None),
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
        created_by_id: int | None = None,
    ) -> TimeEntryResponse:
        """Open a running time entry. Rejected if the job already has one."""
        await self._assert_job(job_id, workspace_id)
        if payload.technician_id is not None:
            await self._assert_technician(payload.technician_id, workspace_id)
        if await self._open_entry(job_id, workspace_id) is not None:
            raise ConflictError("This job already has a running timer")

        entry = TimeEntry(
            workspace_id=workspace_id,
            job_id=job_id,
            technician_id=payload.technician_id,
            started_at=datetime.now(UTC),
            ended_at=None,
            rate=payload.rate,
            note=payload.note,
            created_by_id=created_by_id,
        )
        self.db.add(entry)
        await self.db.flush()
        await self.db.refresh(entry)
        self.log.info("time_clock_in", job_id=str(job_id), entry_id=str(entry.id))
        return self._time_entry_response(entry)

    async def clock_out(self, job_id: uuid.UUID, workspace_id: uuid.UUID) -> TimeEntryResponse:
        """Close the job's running time entry."""
        await self._assert_job(job_id, workspace_id)
        entry = await self._open_entry(job_id, workspace_id)
        if entry is None:
            raise ConflictError("This job has no running timer")
        entry.ended_at = datetime.now(UTC)
        await self.db.flush()
        await self.db.refresh(entry)
        self.log.info("time_clock_out", job_id=str(job_id), entry_id=str(entry.id))
        return self._time_entry_response(entry)

    async def add_time_entry(
        self,
        job_id: uuid.UUID,
        workspace_id: uuid.UUID,
        payload: TimeEntryCreate,
        *,
        created_by_id: int | None = None,
    ) -> TimeEntryResponse:
        """Log a completed time entry from an explicit start/end."""
        await self._assert_job(job_id, workspace_id)
        if payload.technician_id is not None:
            await self._assert_technician(payload.technician_id, workspace_id)
        if payload.ended_at <= payload.started_at:
            raise ConflictError("ended_at must be after started_at")

        entry = TimeEntry(
            workspace_id=workspace_id,
            job_id=job_id,
            technician_id=payload.technician_id,
            started_at=payload.started_at,
            ended_at=payload.ended_at,
            rate=payload.rate,
            note=payload.note,
            created_by_id=created_by_id,
        )
        self.db.add(entry)
        await self.db.flush()
        await self.db.refresh(entry)
        return self._time_entry_response(entry)

    async def delete_time_entry(
        self, job_id: uuid.UUID, workspace_id: uuid.UUID, entry_id: uuid.UUID
    ) -> None:
        await self._assert_job(job_id, workspace_id)
        entry = await assert_workspace_owned(
            self.db,
            TimeEntry,
            entry_id,
            workspace_id,
            TimeEntry.job_id == job_id,
            detail="Time entry not found",
        )
        await self.db.delete(entry)
        await self.db.flush()

    # ------------------------------------------------------------------ #
    # Expenses
    # ------------------------------------------------------------------ #
    async def list_expenses(
        self, job_id: uuid.UUID, workspace_id: uuid.UUID
    ) -> list[JobExpenseResponse]:
        await self._assert_job(job_id, workspace_id)
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
    ) -> JobExpenseResponse:
        await self._assert_job(job_id, workspace_id)
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
        self, job_id: uuid.UUID, workspace_id: uuid.UUID, expense_id: uuid.UUID
    ) -> None:
        await self._assert_job(job_id, workspace_id)
        expense = await assert_workspace_owned(
            self.db,
            JobExpense,
            expense_id,
            workspace_id,
            JobExpense.job_id == job_id,
            detail="Expense not found",
        )
        await self.db.delete(expense)
        await self.db.flush()

    # ------------------------------------------------------------------ #
    # Profitability
    # ------------------------------------------------------------------ #
    async def get_profitability(
        self, job_id: uuid.UUID, workspace_id: uuid.UUID
    ) -> JobProfitability:
        """Compute revenue (linked invoice) minus labor and expense costs."""
        job = await self._assert_job(job_id, workspace_id)

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

        labor_cost = round(labor_cost, 2)
        expense_cost = round(expense_cost, 2)
        total_cost = round(labor_cost + expense_cost, 2)
        profit = round(revenue - total_cost, 2)
        margin = round(profit / revenue, 4) if revenue else None

        return JobProfitability(
            job_id=job_id,
            currency=currency,
            revenue=round(revenue, 2),
            labor_cost=labor_cost,
            expense_cost=expense_cost,
            total_cost=total_cost,
            profit=profit,
            margin=margin,
            total_hours=round(total_hours, 2),
            open_timer=open_timer,
        )
