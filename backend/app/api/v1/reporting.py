"""Operational reporting endpoints (AR aging + job profitability).

Read-only roll-ups computed from invoices and job costing. Available to any
workspace member; every query is workspace-scoped in the service.
"""

from datetime import date, datetime

from fastapi import APIRouter, Query

from app.api.deps import DB, WorkspaceAccess
from app.schemas.reporting import ARAgingReport, JobPnLSummary
from app.services.reporting import ReportingService

router = APIRouter()


@router.get("/ar-aging", response_model=ARAgingReport)
async def ar_aging(
    workspace: WorkspaceAccess,
    db: DB,
    as_of: date | None = Query(None, description="Aging reference date (defaults to today)"),
) -> ARAgingReport:
    """Accounts-receivable aging: outstanding balances bucketed by overdue age."""
    return await ReportingService(db).ar_aging(workspace.id, as_of=as_of)


@router.get("/job-pnl", response_model=JobPnLSummary)
async def job_pnl(
    workspace: WorkspaceAccess,
    db: DB,
    date_from: datetime | None = Query(None, description="Jobs scheduled on or after this time"),
    date_to: datetime | None = Query(None, description="Jobs scheduled on or before this time"),
) -> JobPnLSummary:
    """Aggregate job profitability (revenue minus labor and expenses) over a period."""
    return await ReportingService(db).job_pnl_summary(
        workspace.id, date_from=date_from, date_to=date_to
    )
