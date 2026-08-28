"""Dashboard statistics endpoints."""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends

from app.api.deps import DB, CanReadCRM, CurrentUser, get_workspace, require_capability
from app.core.permissions import Capability, role_can
from app.models.workspace import Workspace
from app.schemas.dashboard import DashboardResponse
from app.schemas.today_queue import TodayQueueResponse
from app.services.dashboard import DashboardService, TodayQueueService

# The dashboard aggregates the CRM: contacts, campaigns, agents, pipeline and
# money. ``crm:read`` is the floor, which excludes the field and lead-technician
# tiers exactly as ``/contacts`` does. Declared on the router so a new dashboard
# endpoint inherits the gate. Finding 2 of docs/technician-role-audit.md.
router = APIRouter(dependencies=[Depends(require_capability(Capability.CRM_READ))])


@router.get("/stats", response_model=DashboardResponse)
async def get_dashboard_stats(
    workspace_id: uuid.UUID,
    current_user: CurrentUser,
    db: DB,
    membership: CanReadCRM,
    workspace: Annotated[Workspace, Depends(get_workspace)],
) -> DashboardResponse:
    """Get dashboard statistics for a workspace.

    Returns comprehensive dashboard data including:
    - Core stats (contacts, campaigns, calls, messages)
    - Recent activity feed
    - Active campaign progress
    - Agent performance metrics
    - Today's overview
    - Appointment metrics

    The dollar-denominated blocks (``revenue_stats``, ``lead_source_roi_stats``)
    require ``reports:view`` and are omitted otherwise, which is the matrix's
    documented intent: the manager tier runs operations but does not get
    reports. Stripped here rather than in the UI, so the numbers never leave the
    server for a caller who may not see them. ``deal_coach_stats`` stays: it is
    pipeline *risk* triage that the sales tier works from daily, not a revenue
    report.

    Results are cached in Redis for 5 minutes to reduce database load.
    """
    service = DashboardService(db)
    dashboard = await service.get_full_dashboard(workspace)
    if not role_can(membership.role, Capability.REPORTS_VIEW):
        return dashboard.model_copy(update={"revenue_stats": None, "lead_source_roi_stats": None})
    return dashboard


@router.get("/today-queue", response_model=TodayQueueResponse)
async def get_today_queue(
    workspace_id: uuid.UUID,
    current_user: CurrentUser,
    db: DB,
    workspace: Annotated[Workspace, Depends(get_workspace)],
) -> TodayQueueResponse:
    """Get the ordered Today mission queue for a workspace.

    Composes pending approvals, nudges due today, fresh ad-library prospect
    batches, draft campaigns awaiting launch, and cold-start setup gaps into
    one prioritized list.
    """
    service = TodayQueueService(db)
    return await service.get_today_queue(workspace.id)
