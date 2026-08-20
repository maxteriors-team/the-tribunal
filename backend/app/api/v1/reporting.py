"""Operational reporting endpoints (AR aging, job profitability, sales, capacity).

Read-only roll-ups computed from invoices, job costing, quotes, jobs and
appointments. Gated on the ``reports:view`` capability, which only the admin tier
holds (see :mod:`app.core.permissions`); every query is workspace-scoped in the
service.
"""

from datetime import date, datetime

from fastapi import APIRouter, Depends, Query

from app.api.deps import DB, CanViewReports, require_route_capabilities
from app.core.permissions import Capability
from app.schemas.reporting import (
    ARAgingReport,
    AttributionGapReport,
    BacklogReport,
    COGSGroupBy,
    COGSReport,
    EstimateCapacityReport,
    JobPnLSummary,
    SalesPerformanceReport,
)
from app.services.inventory import COGSService
from app.services.reporting import CapacityService, ReportingService, SalesPerformanceService
from app.services.reporting.capacity_service import DEFAULT_JOB_HOURS

router = APIRouter(
    dependencies=[
        Depends(require_route_capabilities(Capability.REPORTS_VIEW, Capability.REPORTS_VIEW))
    ]
)


@router.get("/ar-aging", response_model=ARAgingReport)
async def ar_aging(
    membership: CanViewReports,
    db: DB,
    as_of: date | None = Query(None, description="Aging reference date (defaults to today)"),
) -> ARAgingReport:
    """Accounts-receivable aging: outstanding balances bucketed by overdue age."""
    return await ReportingService(db).ar_aging(membership.workspace_id, as_of=as_of)


@router.get("/job-pnl", response_model=JobPnLSummary)
async def job_pnl(
    membership: CanViewReports,
    db: DB,
    date_from: datetime | None = Query(None, description="Jobs scheduled on or after this time"),
    date_to: datetime | None = Query(None, description="Jobs scheduled on or before this time"),
) -> JobPnLSummary:
    """Aggregate job profitability (revenue minus labor and expenses) over a period."""
    return await ReportingService(db).job_pnl_summary(
        membership.workspace_id, date_from=date_from, date_to=date_to
    )


@router.get("/cogs", response_model=COGSReport)
async def cogs(
    membership: CanViewReports,
    db: DB,
    date_from: date | None = Query(
        None,
        description="Stock consumed on or after this date (defaults to the 1st of this month)",
    ),
    date_to: date | None = Query(
        None, description="Stock consumed on or before this date (defaults to today)"
    ),
    group_by: COGSGroupBy = Query("item", description="Breakdown dimension"),
) -> COGSReport:
    """Cost of goods sold: stock consumed in the window, valued at posting cost.

    Shrinkage is reported on its own line rather than inside the total — waste
    hidden in gross margin is waste nobody fixes.
    """
    today = date.today()
    return await COGSService(db).cogs(
        membership.workspace_id,
        date_from=date_from or today.replace(day=1),
        date_to=date_to or today,
        group_by=group_by,
    )


@router.get("/attribution-gap", response_model=AttributionGapReport)
async def attribution_gap(
    membership: CanViewReports,
    db: DB,
    date_from: date | None = Query(
        None,
        description="Contacts created on or after this date (defaults to the 1st of this month)",
    ),
    date_to: date | None = Query(
        None,
        description="Contacts created on or before this date (defaults to today)",
    ),
) -> AttributionGapReport:
    """Surface the share of newly created contacts missing structured attribution."""
    today = date.today()
    return await ReportingService(db).attribution_gap(
        membership.workspace_id,
        date_from=date_from or today.replace(day=1),
        date_to=date_to or today,
    )


@router.get("/sales-performance", response_model=SalesPerformanceReport)
async def sales_performance(
    membership: CanViewReports,
    db: DB,
    date_from: date | None = Query(
        None,
        description="Quotes created on or after this date (defaults to the 1st of this month)",
    ),
    date_to: date | None = Query(
        None,
        description="Quotes created on or before this date (defaults to this month's last day)",
    ),
) -> SalesPerformanceReport:
    """Sales performance: job value, attach rate and close rate over a window."""
    return await SalesPerformanceService(db).sales_performance(
        membership.workspace_id, date_from=date_from, date_to=date_to
    )


@router.get("/backlog", response_model=BacklogReport)
async def backlog(
    membership: CanViewReports,
    db: DB,
    as_of: date | None = Query(None, description="Snapshot date (defaults to today)"),
    weekly_capacity_hours: float | None = Query(
        None,
        gt=0,
        description=(
            "Override the workspace's stored crew capacity, e.g. to model adding "
            "a crew. Required to get backlog_weeks at all when no revenue target "
            "sets crew_capacity_hours_per_week."
        ),
    ),
    default_job_hours: float = Query(
        DEFAULT_JOB_HOURS,
        gt=0,
        description="Hours to assume for a job with no scheduled window",
    ),
) -> BacklogReport:
    """How many weeks of sold work are on the books (the marketing-spend trigger)."""
    return await CapacityService(db).compute_backlog(
        membership.workspace_id,
        as_of=as_of,
        weekly_capacity_hours=weekly_capacity_hours,
        default_job_hours=default_job_hours,
    )


@router.get("/estimate-capacity", response_model=EstimateCapacityReport)
async def estimate_capacity(
    membership: CanViewReports,
    db: DB,
    month: date | None = Query(
        None, description="Any date inside the month to report (defaults to this month)"
    ),
) -> EstimateCapacityReport:
    """Booked estimates versus the month's estimate capacity (the hire trigger)."""
    return await CapacityService(db).compute_estimate_capacity(membership.workspace_id, month)
