"""Apollo-style people-search API.

Workspace-scoped, cross-mission surface to: search people by title / seniority /
location / signal, reveal + verify a person's email on demand, launch a
``web_people`` discovery crawl, and bulk-add people to an outbound mission. The
:class:`ProspectSearchService` owns workspace scoping; this router keeps request
validation + dependency wiring at the boundary.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, status

from app.api.deps import DB, CurrentUser, WorkspaceAccess
from app.api.service_errors import ServiceErrorRoute
from app.core.config import settings
from app.schemas.prospect_search import (
    AddToMissionRequest,
    AddToMissionResponse,
    PeopleDiscoveryRequest,
    PeopleDiscoveryResponse,
    PeopleSearchRequest,
    PeopleSearchResponse,
    RevealEmailResponse,
    RevealPhoneResponse,
)
from app.services.exceptions import ServiceUnavailableError
from app.services.lead_discovery.prospect_search_service import ProspectSearchService
from app.services.rate_limiting.scraping_limiter import enforce_scraping_rate_limit

router = APIRouter(route_class=ServiceErrorRoute)


@router.post("/search", response_model=PeopleSearchResponse)
async def search_people(
    workspace_id: uuid.UUID,
    search_in: PeopleSearchRequest,
    current_user: CurrentUser,
    db: DB,
    workspace: WorkspaceAccess,
) -> PeopleSearchResponse:
    """Search people (named prospects) with signal + firmographic filters."""
    service = ProspectSearchService(db)
    return await service.search_people(workspace_id, search_in)


@router.post("/{prospect_id}/reveal-email", response_model=RevealEmailResponse)
async def reveal_email(
    workspace_id: uuid.UUID,
    prospect_id: uuid.UUID,
    current_user: CurrentUser,
    db: DB,
    workspace: WorkspaceAccess,
) -> RevealEmailResponse:
    """Infer + verify a person's email on demand (pattern + MX/SMTP per config)."""
    service = ProspectSearchService(db)
    return await service.reveal_email(workspace_id, prospect_id)


@router.post("/{prospect_id}/reveal-phone", response_model=RevealPhoneResponse)
async def reveal_phone(
    workspace_id: uuid.UUID,
    prospect_id: uuid.UUID,
    current_user: CurrentUser,
    db: DB,
    workspace: WorkspaceAccess,
) -> RevealPhoneResponse:
    """Scrape the prospect's company site for a published business line."""
    # Live first-party crawl — same per-workspace quota as people discovery.
    await enforce_scraping_rate_limit(workspace_id)
    service = ProspectSearchService(db)
    return await service.reveal_phone(workspace_id, prospect_id)


@router.post(
    "/people-discovery",
    response_model=PeopleDiscoveryResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def launch_people_discovery(
    workspace_id: uuid.UUID,
    discovery_in: PeopleDiscoveryRequest,
    current_user: CurrentUser,
    db: DB,
    workspace: WorkspaceAccess,
) -> PeopleDiscoveryResponse:
    """Launch a ``web_people`` crawl. Enqueues a job the worker runs async."""
    if discovery_in.query and not settings.google_places_api_key:
        raise ServiceUnavailableError(
            "Connect Google Places before searching for companies to crawl.",
            code="people_search_provider_not_configured",
            details={"provider": "google_places", "action": "people_discovery"},
        )

    # Per-workspace quota on the (potentially paid Google Places + crawl) path.
    await enforce_scraping_rate_limit(workspace_id)
    service = ProspectSearchService(db)
    job = await service.launch_people_discovery(
        workspace_id, discovery_in, requested_by_id=current_user.id
    )
    return PeopleDiscoveryResponse.model_validate(job)


@router.post("/add-to-mission", response_model=AddToMissionResponse)
async def add_to_mission(
    workspace_id: uuid.UUID,
    add_in: AddToMissionRequest,
    current_user: CurrentUser,
    db: DB,
    workspace: WorkspaceAccess,
) -> AddToMissionResponse:
    """Bulk-attach selected people to an outbound mission."""
    service = ProspectSearchService(db)
    return await service.add_to_mission(workspace_id, add_in)
