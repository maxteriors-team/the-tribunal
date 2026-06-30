"""Workspace-scoped operational reporting.

Two read-only roll-ups, both tenant-scoped through :mod:`app.db.scope`:

- :meth:`ar_aging` — accounts-receivable aging: outstanding invoice balances
  (``total - amount_paid``) bucketed by how overdue they are relative to an
  ``as_of`` date. Draft/void/paid invoices are excluded (nothing to collect).
- :meth:`job_pnl_summary` — aggregate job profitability over a period: revenue
  from the distinct invoices linked to the period's jobs, minus tracked labor
  (hours × rate) and logged expenses.

Money math uses ``float`` rounded to two decimals, matching the invoice/quote
and job-costing services.
"""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.scope import select_workspace_owned
from app.models.field_service import Job
from app.models.invoice import Invoice
from app.models.job_costing import JobExpense, TimeEntry
from app.schemas.reporting import ARAgingBucket, ARAgingReport, JobPnLSummary

# Invoice statuses with a collectable balance (issued but not settled/cancelled).
_OUTSTANDING_STATUSES = ("sent", "partial", "overdue")


def _duration_hours(started_at: datetime, ended_at: datetime | None) -> float:
    if ended_at is None:
        return 0.0
    return (ended_at - started_at).total_seconds() / 3600.0


def _require_single_currency(currencies: set[str], report: str) -> str:
    """Return the lone currency in ``currencies`` (default USD when empty).

    Summing money across currencies is meaningless, so rather than silently
    emit a wrong total we refuse with 422 and name the clashing currencies.
    """
    present = {code for code in currencies if code}
    if len(present) > 1:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=(
                f"{report} spans multiple currencies "
                f"({', '.join(sorted(present))}); reporting across currencies "
                "is not supported."
            ),
        )
    return next(iter(present), "USD")


class ReportingService:
    """AR aging and job P&L roll-ups for a workspace."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    # ------------------------------------------------------------------ #
    # AR aging
    # ------------------------------------------------------------------ #
    async def ar_aging(
        self, workspace_id: uuid.UUID, *, as_of: date | None = None
    ) -> ARAgingReport:
        """Bucket outstanding receivables by overdue age as of ``as_of``."""
        today = as_of or datetime.now(UTC).date()

        rows = (
            (
                await self.db.execute(
                    select_workspace_owned(
                        Invoice,
                        workspace_id,
                        Invoice.status.in_(_OUTSTANDING_STATUSES),
                    )
                )
            )
            .scalars()
            .all()
        )

        # Ordered buckets; "Current" holds not-yet-due (and undated) balances.
        buckets: list[tuple[str, float, int]] = [
            ("Current", 0.0, 0),
            ("1-30", 0.0, 0),
            ("31-60", 0.0, 0),
            ("61-90", 0.0, 0),
            ("90+", 0.0, 0),
        ]
        currencies: set[str] = set()
        total_outstanding = 0.0
        total_invoices = 0

        for invoice in rows:
            balance = float(invoice.total or 0) - float(invoice.amount_paid or 0)
            if balance <= 0:
                continue
            if invoice.currency:
                currencies.add(invoice.currency)
            total_outstanding += balance
            total_invoices += 1

            if invoice.due_date is None or invoice.due_date >= today:
                index = 0  # Current (not overdue)
            else:
                days = (today - invoice.due_date).days
                if days <= 30:
                    index = 1
                elif days <= 60:
                    index = 2
                elif days <= 90:
                    index = 3
                else:
                    index = 4

            label, amount, count = buckets[index]
            buckets[index] = (label, amount + balance, count + 1)

        currency = _require_single_currency(currencies, "AR aging")
        return ARAgingReport(
            as_of=today,
            currency=currency,
            total_outstanding=round(total_outstanding, 2),
            total_invoices=total_invoices,
            buckets=[
                ARAgingBucket(label=label, amount=round(amount, 2), count=count)
                for label, amount, count in buckets
            ],
        )

    # ------------------------------------------------------------------ #
    # Job P&L summary
    # ------------------------------------------------------------------ #
    async def job_pnl_summary(
        self,
        workspace_id: uuid.UUID,
        *,
        date_from: datetime | None = None,
        date_to: datetime | None = None,
    ) -> JobPnLSummary:
        """Aggregate revenue minus labor and expense cost over a period.

        Jobs are scoped by ``scheduled_start`` within the (optional) window.
        """
        criteria = []
        if date_from is not None:
            criteria.append(Job.scheduled_start >= date_from)
        if date_to is not None:
            criteria.append(Job.scheduled_start <= date_to)

        jobs = (
            (
                await self.db.execute(
                    select_workspace_owned(Job, workspace_id, *criteria)
                )
            )
            .scalars()
            .all()
        )
        job_ids = [job.id for job in jobs]
        invoice_ids = {job.invoice_id for job in jobs if job.invoice_id is not None}

        # Revenue: distinct linked invoices (avoid double-counting shared invoices).
        revenue = 0.0
        currencies: set[str] = set()
        if invoice_ids:
            invoices = (
                (
                    await self.db.execute(
                        select(Invoice).where(
                            Invoice.workspace_id == workspace_id,
                            Invoice.id.in_(invoice_ids),
                        )
                    )
                )
                .scalars()
                .all()
            )
            for invoice in invoices:
                revenue += float(invoice.total or 0)
                if invoice.currency:
                    currencies.add(invoice.currency)
        currency = _require_single_currency(currencies, "Job P&L")

        labor_cost = 0.0
        total_hours = 0.0
        expense_cost = 0.0
        if job_ids:
            entries = (
                (
                    await self.db.execute(
                        select(TimeEntry).where(
                            TimeEntry.workspace_id == workspace_id,
                            TimeEntry.job_id.in_(job_ids),
                        )
                    )
                )
                .scalars()
                .all()
            )
            for entry in entries:
                hours = _duration_hours(entry.started_at, entry.ended_at)
                total_hours += hours
                labor_cost += hours * float(entry.rate or 0)

            expense_amounts = (
                (
                    await self.db.execute(
                        select(JobExpense.amount).where(
                            JobExpense.workspace_id == workspace_id,
                            JobExpense.job_id.in_(job_ids),
                        )
                    )
                )
                .scalars()
                .all()
            )
            expense_cost = sum(float(a or 0) for a in expense_amounts)

        revenue = round(revenue, 2)
        labor_cost = round(labor_cost, 2)
        expense_cost = round(expense_cost, 2)
        total_cost = round(labor_cost + expense_cost, 2)
        profit = round(revenue - total_cost, 2)
        margin = round(profit / revenue, 4) if revenue else None

        return JobPnLSummary(
            date_from=date_from.date() if date_from else None,
            date_to=date_to.date() if date_to else None,
            currency=currency,
            job_count=len(jobs),
            billable_job_count=len(invoice_ids),
            revenue=revenue,
            labor_cost=labor_cost,
            expense_cost=expense_cost,
            total_cost=total_cost,
            profit=profit,
            margin=margin,
            total_hours=round(total_hours, 2),
        )
