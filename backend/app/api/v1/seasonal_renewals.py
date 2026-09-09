"""Single-customer holiday-lighting renewal endpoints.

Sits beside the bulk pre-booking campaign rather than inside it: renewing one
house is a quoting action (it produces a draft quote), not an outreach action, so
it is gated on quote capabilities and lives under the workspace, not under a
campaign.
"""

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.api.deps import (
    DB,
    CanReadQuotes,
    CanWriteQuotes,
    CurrentUser,
    WorkspaceAccess,
    require_route_capabilities,
)
from app.core.permissions import Capability
from app.schemas.quote import QuoteDetailResponse
from app.schemas.seasonal_renewal import RenewalCandidateList, RenewalCandidateResponse
from app.services.seasonal.christmas_renewal import resolve_christmas_season
from app.services.seasonal.renewal_service import (
    ChristmasRenewalService,
    NoPriorSeasonQuoteError,
)

router = APIRouter(
    dependencies=[
        Depends(require_route_capabilities(Capability.QUOTES_READ, Capability.QUOTES_WRITE))
    ]
)
logger = structlog.get_logger()


@router.get("", response_model=RenewalCandidateList)
async def list_renewal_candidates(
    workspace: WorkspaceAccess,
    current_user: CurrentUser,
    db: DB,
    _gate: CanReadQuotes,
    search: str | None = Query(None, max_length=120),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
) -> RenewalCandidateList:
    """Houses this workspace lit in an earlier season, newest signup first."""
    candidates, total = await ChristmasRenewalService(db).list_candidates(
        workspace, search=search, limit=limit, offset=offset
    )
    return RenewalCandidateList(
        items=[RenewalCandidateResponse.model_validate(c) for c in candidates],
        total=total,
        season_year=resolve_christmas_season(workspace).year,
    )


@router.post(
    "/{contact_id}/quote",
    response_model=QuoteDetailResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_renewal_quote(
    contact_id: int,
    workspace: WorkspaceAccess,
    current_user: CurrentUser,
    db: DB,
    _gate: CanWriteQuotes,
) -> QuoteDetailResponse:
    """Draft this season's quote from the customer's last holiday quote."""
    try:
        return await ChristmasRenewalService(db).create_renewal_quote(
            workspace, contact_id, created_by_id=current_user.id
        )
    except NoPriorSeasonQuoteError as exc:
        # 404 rather than 409: from the caller's side the renewable thing simply
        # is not there. Covers both "never bought" and "quote since deleted",
        # which keeps the endpoint from confirming whether an arbitrary contact
        # id exists in this workspace.
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
