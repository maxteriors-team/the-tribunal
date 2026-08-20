"""Monthly revenue target endpoints, plus the month-pace report.

Thin transport over
:class:`app.services.reporting.revenue_target_service.RevenueTargetService`.
Targets are addressed by **month**, not by id: ``period_month`` is any date
inside the month and the service normalizes it to the 1st, so ``PUT`` is a true
idempotent upsert.

Access follows the neighbouring surfaces, both gates capability-based (the
preferred style for new endpoints — see :mod:`app.api.deps`). Reads require
``reports:view`` like :mod:`app.api.v1.reporting`: a revenue goal and the pace
against it is the same class of information as the P&L. Writes require
``workspace:manage`` because the goal is the owner's commitment, not an
operational setting a dispatcher should be able to move. Both resolve the
caller's workspace membership, and every query underneath is workspace-scoped in
the service.

Fixed paths (``/pace``, ``/bulk``) are declared before ``/{period_month}``:
FastAPI matches in declaration order, and ``pace`` is not a parsable date.
"""

import uuid
from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, Path, Query, status

from app.api.deps import (
    DB,
    CanManageWorkspace,
    CanViewReports,
    require_route_capabilities,
)
from app.api.service_errors import ServiceErrorRoute
from app.core.permissions import Capability
from app.schemas.revenue_target import (
    RevenuePace,
    RevenueTargetBulkUpsert,
    RevenueTargetList,
    RevenueTargetResponse,
    RevenueTargetUpsert,
)
from app.services.reporting import RevenueTargetService

router = APIRouter(
    route_class=ServiceErrorRoute,
    dependencies=[
        Depends(require_route_capabilities(Capability.REPORTS_VIEW, Capability.WORKSPACE_MANAGE))
    ],
)

PeriodMonth = Annotated[
    date,
    Path(description="Any date inside the target month; normalized to the 1st"),
]


@router.get("", response_model=RevenueTargetList)
async def list_revenue_targets(
    workspace_id: uuid.UUID,
    membership: CanViewReports,
    db: DB,
    year: Annotated[int | None, Query(ge=2000, le=2100, description="Narrow to one year")] = None,
) -> RevenueTargetList:
    """List a workspace's monthly revenue targets, oldest month first."""
    return await RevenueTargetService(db).list_targets(workspace_id, year=year)


@router.get("/pace", response_model=RevenuePace)
async def get_revenue_pace(
    workspace_id: uuid.UUID,
    membership: CanViewReports,
    db: DB,
    month: Annotated[
        date | None,
        Query(description="Any date inside the month to report (defaults to this month)"),
    ] = None,
) -> RevenuePace:
    """Report whether a month is on pace to hit its revenue goal.

    Months with no stored target still report their actuals, flagged with
    ``has_target: false``.
    """
    return await RevenueTargetService(db).get_pace(workspace_id, month)


@router.put("/bulk", response_model=RevenueTargetList)
async def bulk_upsert_revenue_targets(
    workspace_id: uuid.UUID,
    payload: RevenueTargetBulkUpsert,
    membership: CanManageWorkspace,
    db: DB,
) -> RevenueTargetList:
    """Set a season's worth of targets in one atomic statement."""
    return await RevenueTargetService(db).bulk_upsert(workspace_id, payload)


@router.put("", response_model=RevenueTargetResponse)
async def upsert_revenue_target(
    workspace_id: uuid.UUID,
    payload: RevenueTargetUpsert,
    membership: CanManageWorkspace,
    db: DB,
) -> RevenueTargetResponse:
    """Set (or replace) one month's revenue target."""
    return await RevenueTargetService(db).upsert_target(workspace_id, payload)


@router.get("/{period_month}", response_model=RevenueTargetResponse)
async def get_revenue_target(
    workspace_id: uuid.UUID,
    period_month: PeriodMonth,
    membership: CanViewReports,
    db: DB,
) -> RevenueTargetResponse:
    """Fetch one month's revenue target."""
    return await RevenueTargetService(db).get_target(workspace_id, period_month)


@router.delete("/{period_month}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_revenue_target(
    workspace_id: uuid.UUID,
    period_month: PeriodMonth,
    membership: CanManageWorkspace,
    db: DB,
) -> None:
    """Clear one month's revenue target."""
    await RevenueTargetService(db).delete_target(workspace_id, period_month)
