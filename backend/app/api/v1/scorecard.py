"""Receptionist scorecard endpoint — the owner-facing retention surface."""

import uuid
from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, Query

from app.api.deps import DB, CurrentUser, get_workspace
from app.models.workspace import Workspace
from app.schemas.scorecard import ReceptionistScorecard
from app.services.dashboard import ScorecardService

router = APIRouter()


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
