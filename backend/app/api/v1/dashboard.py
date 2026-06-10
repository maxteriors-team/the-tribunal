"""Dashboard statistics endpoints."""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends

from app.api.deps import DB, CurrentUser, get_workspace
from app.models.workspace import Workspace
from app.schemas.dashboard import DashboardResponse
from app.schemas.today_queue import TodayQueueResponse
from app.services.dashboard import DashboardService, TodayQueueService

router = APIRouter()


@router.get("/stats", response_model=DashboardResponse)
async def get_dashboard_stats(
    workspace_id: uuid.UUID,
    current_user: CurrentUser,
    db: DB,
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

    Results are cached in Redis for 5 minutes to reduce database load.
    """
    service = DashboardService(db)
    return await service.get_full_dashboard(workspace)


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
