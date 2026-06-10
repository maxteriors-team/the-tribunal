"""Ad Library prospecting API endpoints.

Pull advertisers from public ad libraries (Meta Ad Library, Google Ads
Transparency), surface the ones running consistently but **not** iterating
creatives, and ingest qualified advertisers into the CRM. The
:class:`AdLibraryService` owns workspace scoping; this router keeps request
validation + dependency wiring at the boundary.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Query, status

from app.api.deps import DB, CurrentUser, WorkspaceAccess
from app.api.service_errors import ServiceErrorRoute
from app.models.ad_advertiser import AdPlatform
from app.schemas.ad_advertiser import AdAdvertiserDetail, PaginatedAdAdvertisers
from app.schemas.ad_library import (
    AdLibrarySearchRequest,
    AdMonitorCreate,
    AdMonitorResponse,
    AdMonitorUpdate,
    AdvertiserBulkPromoteRequest,
    AdvertiserBulkPromoteResult,
    AdvertiserPromoteRequest,
    AdvertiserPromoteResult,
)
from app.schemas.lead_discovery_job import LeadDiscoveryJobResponse
from app.services.ad_intelligence.ad_library_service import AdLibraryService

router = APIRouter(route_class=ServiceErrorRoute)


@router.post(
    "/search",
    response_model=LeadDiscoveryJobResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def create_search(
    workspace_id: uuid.UUID,
    search_in: AdLibrarySearchRequest,
    current_user: CurrentUser,
    db: DB,
    workspace: WorkspaceAccess,
) -> LeadDiscoveryJobResponse:
    """Launch an ad-library search.

    Enqueues a discovery job the ad-library worker runs asynchronously; poll
    ``GET /jobs/{id}`` for status.
    """
    service = AdLibraryService(db)
    job = await service.create_search_job(workspace_id, search_in, requested_by_id=current_user.id)
    return LeadDiscoveryJobResponse.model_validate(job)


@router.get("/jobs/{job_id}", response_model=LeadDiscoveryJobResponse)
async def get_job(
    workspace_id: uuid.UUID,
    job_id: uuid.UUID,
    current_user: CurrentUser,
    db: DB,
    workspace: WorkspaceAccess,
) -> LeadDiscoveryJobResponse:
    """Return the status of an ad-library discovery job."""
    service = AdLibraryService(db)
    job = await service.get_job(workspace_id, job_id)
    return LeadDiscoveryJobResponse.model_validate(job)


@router.get("/advertisers", response_model=PaginatedAdAdvertisers)
async def list_advertisers(
    workspace_id: uuid.UUID,
    current_user: CurrentUser,
    db: DB,
    workspace: WorkspaceAccess,
    platform: AdPlatform | None = Query(default=None),
    only_qualified: bool = Query(
        default=False,
        description="Apply ICP floors + exclude prolific testers.",
    ),
    contact_traced: bool | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=25, ge=1, le=100),
) -> PaginatedAdAdvertisers:
    """List tracked advertisers ranked by opportunity score (ICP fit)."""
    service = AdLibraryService(db)
    return await service.list_advertisers(
        workspace_id,
        platform=platform,
        only_qualified=only_qualified,
        contact_traced=contact_traced,
        page=page,
        page_size=page_size,
    )


@router.get("/advertisers/{advertiser_id}", response_model=AdAdvertiserDetail)
async def get_advertiser(
    workspace_id: uuid.UUID,
    advertiser_id: uuid.UUID,
    current_user: CurrentUser,
    db: DB,
    workspace: WorkspaceAccess,
) -> AdAdvertiserDetail:
    """Return one advertiser with creatives, signal breakdown, and traced contact."""
    service = AdLibraryService(db)
    return await service.get_advertiser_detail(workspace_id, advertiser_id)


@router.post(
    "/advertisers/{advertiser_id}/promote",
    response_model=AdvertiserPromoteResult,
)
async def promote_advertiser(
    workspace_id: uuid.UUID,
    advertiser_id: uuid.UUID,
    promote_in: AdvertiserPromoteRequest,
    current_user: CurrentUser,
    db: DB,
    workspace: WorkspaceAccess,
) -> AdvertiserPromoteResult:
    """Promote one advertiser into the CRM (advertiser -> prospect -> contact)."""
    service = AdLibraryService(db)
    return await service.promote_advertiser(workspace_id, advertiser_id, promote_in)


@router.post("/advertisers/bulk-promote", response_model=AdvertiserBulkPromoteResult)
async def bulk_promote_advertisers(
    workspace_id: uuid.UUID,
    promote_in: AdvertiserBulkPromoteRequest,
    current_user: CurrentUser,
    db: DB,
    workspace: WorkspaceAccess,
) -> AdvertiserBulkPromoteResult:
    """Promote many advertisers into the CRM in one call."""
    service = AdLibraryService(db)
    return await service.bulk_promote(workspace_id, promote_in)


@router.get("/monitors", response_model=list[AdMonitorResponse])
async def list_monitors(
    workspace_id: uuid.UUID,
    current_user: CurrentUser,
    db: DB,
    workspace: WorkspaceAccess,
) -> list[AdMonitorResponse]:
    """List saved ad-library monitors (recurring ICP searches)."""
    service = AdLibraryService(db)
    return await service.list_monitors(workspace_id)


@router.post(
    "/monitors",
    response_model=AdMonitorResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_monitor(
    workspace_id: uuid.UUID,
    monitor_in: AdMonitorCreate,
    current_user: CurrentUser,
    db: DB,
    workspace: WorkspaceAccess,
) -> AdMonitorResponse:
    """Create a saved monitor that re-scans on a schedule."""
    service = AdLibraryService(db)
    return await service.create_monitor(workspace_id, monitor_in, created_by_id=current_user.id)


@router.patch("/monitors/{monitor_id}", response_model=AdMonitorResponse)
async def update_monitor(
    workspace_id: uuid.UUID,
    monitor_id: uuid.UUID,
    monitor_in: AdMonitorUpdate,
    current_user: CurrentUser,
    db: DB,
    workspace: WorkspaceAccess,
) -> AdMonitorResponse:
    """Update a saved monitor's search / thresholds / schedule / active flag."""
    service = AdLibraryService(db)
    return await service.update_monitor(workspace_id, monitor_id, monitor_in)


@router.delete("/monitors/{monitor_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_monitor(
    workspace_id: uuid.UUID,
    monitor_id: uuid.UUID,
    current_user: CurrentUser,
    db: DB,
    workspace: WorkspaceAccess,
) -> None:
    """Delete a saved monitor."""
    service = AdLibraryService(db)
    await service.delete_monitor(workspace_id, monitor_id)
