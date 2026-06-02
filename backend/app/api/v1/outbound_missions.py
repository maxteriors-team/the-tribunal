"""Outbound Mission / Lead Miner API endpoints.

The service layer owns outbound mission lifecycle, prospect selection, stats,
sequence overview, discovery-job lookup, enrichment aggregation, and workspace
foreign-key validation. This router keeps request validation and dependency
wiring at the API boundary.
"""

from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, Query, status

from app.api.deps import DB, CurrentUser, WorkspaceAccess
from app.api.service_errors import ServiceErrorRoute
from app.models.lead_discovery_job import DiscoveryJobStatus, DiscoverySourceType
from app.models.lead_prospect import ProspectIdentityKind, ProspectStatus
from app.models.outbound_mission import MissionStatus, OutboundMission
from app.models.outbound_sequence import SequenceEnrollmentStatus
from app.schemas.lead_discovery_job import LeadDiscoveryJobResponse, PaginatedLeadDiscoveryJobs
from app.schemas.lead_prospect import (
    LeadEnrichmentResultResponse,
    LeadProspectResponse,
    PaginatedLeadProspects,
)
from app.schemas.outbound_mission import (
    OutboundMissionCreate,
    OutboundMissionResponse,
    OutboundMissionStatsResponse,
    OutboundMissionUpdate,
    PaginatedOutboundMissions,
)
from app.schemas.outbound_sequence import OutboundSequenceEnrollmentResponse
from app.services.outbound.mission_service import OutboundMissionService

router = APIRouter(route_class=ServiceErrorRoute)


@router.post(
    "",
    response_model=OutboundMissionResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_mission(
    workspace_id: uuid.UUID,
    mission_in: OutboundMissionCreate,
    current_user: CurrentUser,
    db: DB,
    workspace: WorkspaceAccess,
) -> OutboundMission:
    """Create a new outbound mission in DRAFT status."""
    service = OutboundMissionService(db)
    return await service.create_mission(
        workspace_id,
        mission_in,
        created_by_id=current_user.id,
    )


@router.get("", response_model=PaginatedOutboundMissions)
async def list_missions(
    workspace_id: uuid.UUID,
    current_user: CurrentUser,
    db: DB,
    workspace: WorkspaceAccess,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=100),
    status_filter: MissionStatus | None = Query(default=None, alias="status"),
    objective: str | None = Query(default=None, max_length=50),
    search: str | None = Query(default=None, max_length=255),
) -> PaginatedOutboundMissions:
    """List outbound missions in a workspace with optional filters."""
    service = OutboundMissionService(db)
    return await service.list_missions(
        workspace_id,
        page=page,
        page_size=page_size,
        status_filter=status_filter,
        objective=objective,
        search=search,
    )


@router.get("/{mission_id}", response_model=OutboundMissionResponse)
async def get_mission(
    workspace_id: uuid.UUID,
    mission_id: uuid.UUID,
    current_user: CurrentUser,
    db: DB,
    workspace: WorkspaceAccess,
) -> OutboundMission:
    """Fetch a single outbound mission."""
    service = OutboundMissionService(db)
    return await service.get_mission_or_404(mission_id, workspace_id)


@router.put("/{mission_id}", response_model=OutboundMissionResponse)
@router.patch("/{mission_id}", response_model=OutboundMissionResponse)
async def update_mission(
    workspace_id: uuid.UUID,
    mission_id: uuid.UUID,
    mission_in: OutboundMissionUpdate,
    current_user: CurrentUser,
    db: DB,
    workspace: WorkspaceAccess,
) -> OutboundMission:
    """Partially update an outbound mission."""
    service = OutboundMissionService(db)
    return await service.update_mission(workspace_id, mission_id, mission_in)


@router.delete("/{mission_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_mission(
    workspace_id: uuid.UUID,
    mission_id: uuid.UUID,
    current_user: CurrentUser,
    db: DB,
    workspace: WorkspaceAccess,
) -> None:
    """Delete a draft or archived mission."""
    service = OutboundMissionService(db)
    await service.delete_mission(workspace_id, mission_id)


@router.post("/{mission_id}/start", response_model=OutboundMissionResponse)
async def start_mission(
    workspace_id: uuid.UUID,
    mission_id: uuid.UUID,
    current_user: CurrentUser,
    db: DB,
    workspace: WorkspaceAccess,
) -> OutboundMission:
    """Start (or resume) a mission by moving DRAFT/PAUSED to ACTIVE."""
    service = OutboundMissionService(db)
    return await service.start_mission(workspace_id, mission_id)


@router.post("/{mission_id}/pause", response_model=OutboundMissionResponse)
async def pause_mission(
    workspace_id: uuid.UUID,
    mission_id: uuid.UUID,
    current_user: CurrentUser,
    db: DB,
    workspace: WorkspaceAccess,
) -> OutboundMission:
    """Pause an active mission."""
    service = OutboundMissionService(db)
    return await service.pause_mission(workspace_id, mission_id)


@router.post("/{mission_id}/resume", response_model=OutboundMissionResponse)
async def resume_mission(
    workspace_id: uuid.UUID,
    mission_id: uuid.UUID,
    current_user: CurrentUser,
    db: DB,
    workspace: WorkspaceAccess,
) -> OutboundMission:
    """Resume a paused mission."""
    service = OutboundMissionService(db)
    return await service.resume_mission(workspace_id, mission_id)


@router.post("/{mission_id}/complete", response_model=OutboundMissionResponse)
async def complete_mission(
    workspace_id: uuid.UUID,
    mission_id: uuid.UUID,
    current_user: CurrentUser,
    db: DB,
    workspace: WorkspaceAccess,
) -> OutboundMission:
    """Mark a mission as completed."""
    service = OutboundMissionService(db)
    return await service.complete_mission(workspace_id, mission_id)


@router.post("/{mission_id}/archive", response_model=OutboundMissionResponse)
async def archive_mission(
    workspace_id: uuid.UUID,
    mission_id: uuid.UUID,
    current_user: CurrentUser,
    db: DB,
    workspace: WorkspaceAccess,
) -> OutboundMission:
    """Archive a mission in any non-archived state."""
    service = OutboundMissionService(db)
    return await service.archive_mission(workspace_id, mission_id)


@router.get("/{mission_id}/stats", response_model=OutboundMissionStatsResponse)
async def get_mission_stats(
    workspace_id: uuid.UUID,
    mission_id: uuid.UUID,
    current_user: CurrentUser,
    db: DB,
    workspace: WorkspaceAccess,
) -> OutboundMissionStatsResponse:
    """Return mission counters with derived reply / qualification / booking rates."""
    service = OutboundMissionService(db)
    return await service.get_mission_stats(workspace_id, mission_id)


@router.get(
    "/{mission_id}/prospects",
    response_model=PaginatedLeadProspects,
)
async def list_mission_prospects(
    workspace_id: uuid.UUID,
    mission_id: uuid.UUID,
    current_user: CurrentUser,
    db: DB,
    workspace: WorkspaceAccess,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=100),
    status_filter: ProspectStatus | None = Query(default=None, alias="status"),
    identity_kind: ProspectIdentityKind | None = None,
    source_type: str | None = Query(default=None, max_length=50),
    min_score: int | None = Query(default=None, ge=0),
    max_score: int | None = Query(default=None, ge=0),
    has_email: bool | None = None,
    has_phone: bool | None = None,
    search: str | None = Query(default=None, max_length=255),
) -> PaginatedLeadProspects:
    """List prospects belonging to a mission with filter + pagination."""
    service = OutboundMissionService(db)
    return await service.list_mission_prospects(
        workspace_id,
        mission_id,
        page=page,
        page_size=page_size,
        status_filter=status_filter,
        identity_kind=identity_kind,
        source_type=source_type,
        min_score=min_score,
        max_score=max_score,
        has_email=has_email,
        has_phone=has_phone,
        search=search,
    )


@router.get(
    "/{mission_id}/prospects/{prospect_id}",
    response_model=LeadProspectResponse,
)
async def get_mission_prospect(
    workspace_id: uuid.UUID,
    mission_id: uuid.UUID,
    prospect_id: uuid.UUID,
    current_user: CurrentUser,
    db: DB,
    workspace: WorkspaceAccess,
) -> LeadProspectResponse:
    """Fetch a single prospect that belongs to ``mission_id``."""
    service = OutboundMissionService(db)
    prospect = await service.get_mission_prospect_or_404(
        mission_id,
        prospect_id,
        workspace_id,
    )
    return LeadProspectResponse.model_validate(prospect)


@router.post(
    "/{mission_id}/prospects/{prospect_id}/select",
    response_model=LeadProspectResponse,
)
async def select_mission_prospect(
    workspace_id: uuid.UUID,
    mission_id: uuid.UUID,
    prospect_id: uuid.UUID,
    current_user: CurrentUser,
    db: DB,
    workspace: WorkspaceAccess,
) -> LeadProspectResponse:
    """Select a prospect for outreach by moving it to QUEUED."""
    service = OutboundMissionService(db)
    prospect = await service.select_mission_prospect(workspace_id, mission_id, prospect_id)
    return LeadProspectResponse.model_validate(prospect)


@router.post(
    "/{mission_id}/prospects/{prospect_id}/suppress",
    response_model=LeadProspectResponse,
)
async def suppress_mission_prospect(
    workspace_id: uuid.UUID,
    mission_id: uuid.UUID,
    prospect_id: uuid.UUID,
    current_user: CurrentUser,
    db: DB,
    workspace: WorkspaceAccess,
    reason: str | None = Query(default=None, max_length=255),
) -> LeadProspectResponse:
    """Suppress a prospect as do-not-contact."""
    service = OutboundMissionService(db)
    prospect = await service.suppress_mission_prospect(
        workspace_id,
        mission_id,
        prospect_id,
        reason=reason,
    )
    return LeadProspectResponse.model_validate(prospect)


@router.get(
    "/{mission_id}/prospects/{prospect_id}/enrichment",
    response_model=list[LeadEnrichmentResultResponse],
)
async def list_prospect_enrichment_results(
    workspace_id: uuid.UUID,
    mission_id: uuid.UUID,
    prospect_id: uuid.UUID,
    current_user: CurrentUser,
    db: DB,
    workspace: WorkspaceAccess,
    limit: int = Query(100, ge=1, le=500),
) -> list[LeadEnrichmentResultResponse]:
    """List enrichment audit rows for a single prospect, newest first."""
    service = OutboundMissionService(db)
    return await service.list_prospect_enrichment_results(
        workspace_id,
        mission_id,
        prospect_id,
        limit=limit,
    )


@router.get(
    "/{mission_id}/discovery-jobs",
    response_model=PaginatedLeadDiscoveryJobs,
)
async def list_mission_discovery_jobs(
    workspace_id: uuid.UUID,
    mission_id: uuid.UUID,
    current_user: CurrentUser,
    db: DB,
    workspace: WorkspaceAccess,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=100),
    status_filter: DiscoveryJobStatus | None = Query(default=None, alias="status"),
    source_type: DiscoverySourceType | None = None,
) -> PaginatedLeadDiscoveryJobs:
    """List discovery jobs that emitted prospects into this mission."""
    service = OutboundMissionService(db)
    return await service.list_mission_discovery_jobs(
        workspace_id,
        mission_id,
        page=page,
        page_size=page_size,
        status_filter=status_filter,
        source_type=source_type,
    )


@router.get(
    "/{mission_id}/discovery-jobs/{job_id}",
    response_model=LeadDiscoveryJobResponse,
)
async def get_mission_discovery_job(
    workspace_id: uuid.UUID,
    mission_id: uuid.UUID,
    job_id: uuid.UUID,
    current_user: CurrentUser,
    db: DB,
    workspace: WorkspaceAccess,
) -> LeadDiscoveryJobResponse:
    """Fetch a single discovery job."""
    service = OutboundMissionService(db)
    job = await service.get_mission_discovery_job(workspace_id, mission_id, job_id)
    return LeadDiscoveryJobResponse.model_validate(job)


@router.get("/{mission_id}/enrichment-status")
async def get_mission_enrichment_status(
    workspace_id: uuid.UUID,
    mission_id: uuid.UUID,
    current_user: CurrentUser,
    db: DB,
    workspace: WorkspaceAccess,
) -> dict[str, Any]:
    """Aggregate enrichment status for a mission."""
    service = OutboundMissionService(db)
    return await service.get_mission_enrichment_status(workspace_id, mission_id)


@router.get("/{mission_id}/sequence")
async def get_mission_sequence_overview(
    workspace_id: uuid.UUID,
    mission_id: uuid.UUID,
    current_user: CurrentUser,
    db: DB,
    workspace: WorkspaceAccess,
) -> dict[str, Any]:
    """Return the mission's default sequence and enrollment counters."""
    service = OutboundMissionService(db)
    return await service.get_mission_sequence_overview(workspace_id, mission_id)


@router.get(
    "/{mission_id}/enrollments",
    response_model=list[OutboundSequenceEnrollmentResponse],
)
async def list_mission_enrollments(
    workspace_id: uuid.UUID,
    mission_id: uuid.UUID,
    current_user: CurrentUser,
    db: DB,
    workspace: WorkspaceAccess,
    status_filter: SequenceEnrollmentStatus | None = Query(default=None, alias="status"),
    limit: int = Query(100, ge=1, le=500),
) -> list[OutboundSequenceEnrollmentResponse]:
    """List sequence enrollments for the mission."""
    service = OutboundMissionService(db)
    return await service.list_mission_enrollments(
        workspace_id,
        mission_id,
        status_filter=status_filter,
        limit=limit,
    )
