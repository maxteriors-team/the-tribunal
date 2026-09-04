"""Supervisor-only receptionist and technician activity scorecard endpoints."""

import uuid
from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query

from app.api.deps import DB, CurrentUser, get_workspace, require_route_capabilities
from app.core.permissions import Capability
from app.models.workspace import Workspace
from app.schemas.scorecard import (
    OfficeRepScorecardRow,
    ReceptionistScorecard,
    TechnicianActivityScorecardRow,
)
from app.services.dashboard import ScorecardService

router = APIRouter(
    dependencies=[
        Depends(
            require_route_capabilities(
                Capability.REPORTS_VIEW,
                Capability.REPORTS_VIEW,
            )
        )
    ]
)


@router.get("", response_model=ReceptionistScorecard)
async def get_receptionist_scorecard(
    workspace_id: uuid.UUID,
    current_user: CurrentUser,
    db: DB,
    workspace: Annotated[Workspace, Depends(get_workspace)],
    start_date: Annotated[date | None, Query()] = None,
    end_date: Annotated[date | None, Query()] = None,
) -> ReceptionistScorecard:
    """Return the receptionist scorecard for a workspace over a date range.

    Aggregates calls answered, appointments booked, revenue/deposits booked,
    missed calls and missed-call recovery (via the text-back/voicemail flow),
    top call reasons, after-hours coverage, and average handle time.

    The range defaults to the last 30 days when ``start_date``/``end_date`` are
    omitted; both bounds are inclusive calendar dates.
    """
    service = ScorecardService(db)
    return await service.get_scorecard(workspace, start_date, end_date)


@router.get("/technicians", response_model=list[TechnicianActivityScorecardRow])
async def get_technician_activity_scorecard(
    workspace_id: uuid.UUID,
    current_user: CurrentUser,
    db: DB,
    workspace: Annotated[Workspace, Depends(get_workspace)],
    start_date: Annotated[date | None, Query()] = None,
    end_date: Annotated[date | None, Query()] = None,
) -> list[TechnicianActivityScorecardRow]:
    """Return activity context for each workspace technician over the date range."""
    service = ScorecardService(db)
    return await service.get_technician_activity(workspace, start_date, end_date)


@router.get("/office-reps", response_model=list[OfficeRepScorecardRow])
async def get_office_rep_activity_scorecard(
    workspace_id: uuid.UUID,
    current_user: CurrentUser,
    db: DB,
    workspace: Annotated[Workspace, Depends(get_workspace)],
    start_date: Annotated[date | None, Query()] = None,
    end_date: Annotated[date | None, Query()] = None,
) -> list[OfficeRepScorecardRow]:
    """Return private admin/CSR activity profiles over the selected date range."""
    if start_date is not None and end_date is not None and abs((end_date - start_date).days) > 365:
        raise HTTPException(status_code=422, detail="Date range cannot exceed 366 days")
    return await ScorecardService(db).get_office_rep_activity(workspace, start_date, end_date)
