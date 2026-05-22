"""Outbound Mission / Lead Miner API endpoints.

Exposes the full outbound mission lifecycle (create, list, detail, update,
lifecycle transitions, delete), per-mission prospect listing/selection, mission
stats with derived rates, discovery job inspection, enrichment status
aggregation, and a sequence overview that surfaces the mission's default
sequence plus enrollment counts.

All endpoints are scoped to ``/workspaces/{workspace_id}/outbound-missions``
and enforce the standard workspace-membership dependency (``get_workspace``).
Foreign-key references in request bodies (offer, agent, sequence) are validated
against the caller's workspace before being persisted to prevent cross-tenant
references.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select

from app.api.crud import get_or_404
from app.api.deps import DB, CurrentUser, get_workspace
from app.db.pagination import paginate
from app.db.scope import apply_workspace_scope
from app.models.agent import Agent
from app.models.lead_discovery_job import (
    DiscoveryJobStatus,
    DiscoverySourceType,
    LeadDiscoveryJob,
)
from app.models.lead_prospect import (
    EnrichmentProvider,
    EnrichmentResultStatus,
    LeadEnrichmentResult,
    LeadProspect,
    ProspectIdentityKind,
    ProspectStatus,
)
from app.models.offer import Offer
from app.models.outbound_mission import MissionStatus, OutboundMission
from app.models.outbound_sequence import (
    OutboundSequence,
    OutboundSequenceEnrollment,
    SequenceEnrollmentStatus,
)
from app.models.workspace import Workspace
from app.schemas.lead_discovery_job import (
    LeadDiscoveryJobResponse,
    PaginatedLeadDiscoveryJobs,
)
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
from app.schemas.outbound_sequence import (
    OutboundSequenceEnrollmentResponse,
    OutboundSequenceResponse,
)

router = APIRouter()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


# Mission states that allow mutation (PUT and DELETE).
_MUTABLE_STATUSES: frozenset[MissionStatus] = frozenset(
    {MissionStatus.DRAFT, MissionStatus.PAUSED, MissionStatus.ARCHIVED}
)
# Mission states that can transition to ACTIVE via /start or /resume.
_STARTABLE_STATUSES: frozenset[MissionStatus] = frozenset(
    {MissionStatus.DRAFT, MissionStatus.PAUSED}
)


async def _ensure_workspace_scoped_fk(
    db: DB,
    model: type[Agent | Offer | OutboundSequence],
    fk_id: uuid.UUID | None,
    workspace_id: uuid.UUID,
    label: str,
) -> None:
    """Validate that ``fk_id`` (if set) refers to a row owned by ``workspace_id``."""
    if fk_id is None:
        return
    result = await db.execute(
        apply_workspace_scope(
            select(model.id).where(model.id == fk_id),
            model,
            workspace_id,
        )
    )
    if result.scalar_one_or_none() is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"{label} not found",
        )


async def _validate_mission_fks(
    db: DB,
    workspace_id: uuid.UUID,
    *,
    offer_id: uuid.UUID | None,
    default_agent_id: uuid.UUID | None,
    default_sequence_id: uuid.UUID | None,
) -> None:
    """Validate offer, agent, and sequence FKs against ``workspace_id``."""
    await _ensure_workspace_scoped_fk(db, Offer, offer_id, workspace_id, "Offer")
    await _ensure_workspace_scoped_fk(db, Agent, default_agent_id, workspace_id, "Agent")
    await _ensure_workspace_scoped_fk(
        db,
        OutboundSequence,
        default_sequence_id,
        workspace_id,
        "Outbound sequence",
    )


def _stats_response(mission: OutboundMission) -> OutboundMissionStatsResponse:
    """Compute derived rate fields for the mission stats response."""
    contacted = mission.total_prospects_contacted
    replied = mission.total_prospects_replied
    qualified = mission.total_prospects_qualified
    booked = mission.total_appointments_booked

    reply_rate = (replied / contacted) if contacted > 0 else 0.0
    qualification_rate = (qualified / contacted) if contacted > 0 else 0.0
    booking_rate = (booked / contacted) if contacted > 0 else 0.0

    return OutboundMissionStatsResponse(
        mission_id=mission.id,
        total_prospects_discovered=mission.total_prospects_discovered,
        total_prospects_enriched=mission.total_prospects_enriched,
        total_prospects_contacted=contacted,
        total_prospects_replied=replied,
        total_prospects_qualified=qualified,
        total_contacts_created=mission.total_contacts_created,
        total_appointments_booked=booked,
        reply_rate=reply_rate,
        qualification_rate=qualification_rate,
        booking_rate=booking_rate,
    )


async def _get_mission_or_404(
    db: DB, mission_id: uuid.UUID, workspace_id: uuid.UUID
) -> OutboundMission:
    """Fetch a mission scoped to ``workspace_id`` or raise 404."""
    return await get_or_404(
        db,
        OutboundMission,
        mission_id,
        workspace_id=workspace_id,
        detail="Outbound mission not found",
    )


async def _get_mission_prospect_or_404(
    db: DB,
    mission_id: uuid.UUID,
    prospect_id: uuid.UUID,
    workspace_id: uuid.UUID,
) -> LeadProspect:
    """Fetch a prospect that belongs to ``mission_id`` or raise 404."""
    await _get_mission_or_404(db, mission_id, workspace_id)
    prospect = await get_or_404(
        db,
        LeadProspect,
        prospect_id,
        workspace_id=workspace_id,
        detail="Lead prospect not found",
    )
    if prospect.mission_id != mission_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Lead prospect not found",
        )
    return prospect


def _transition_mission(
    mission: OutboundMission,
    *,
    target: MissionStatus,
    allowed_from: frozenset[MissionStatus],
    action: str,
) -> None:
    """Apply a status transition with lifecycle-timestamp bookkeeping.

    Raises HTTP 400 if the current status is not in ``allowed_from``.
    """
    if mission.status not in allowed_from:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Cannot {action} mission in status '{mission.status.value}'",
        )

    now = datetime.now(UTC)
    mission.status = target

    if target == MissionStatus.ACTIVE:
        if mission.started_at is None:
            mission.started_at = now
        mission.paused_at = None
    elif target == MissionStatus.PAUSED:
        mission.paused_at = now
    elif target == MissionStatus.COMPLETED:
        mission.completed_at = now
    elif target == MissionStatus.ARCHIVED:
        mission.archived_at = now


# ---------------------------------------------------------------------------
# Mission CRUD + lifecycle
# ---------------------------------------------------------------------------


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
    workspace: Annotated[Workspace, Depends(get_workspace)],
) -> OutboundMission:
    """Create a new outbound mission in DRAFT status."""
    await _validate_mission_fks(
        db,
        workspace_id,
        offer_id=mission_in.offer_id,
        default_agent_id=mission_in.default_agent_id,
        default_sequence_id=mission_in.default_sequence_id,
    )

    mission = OutboundMission(
        workspace_id=workspace_id,
        created_by_id=current_user.id,
        **mission_in.model_dump(),
    )
    db.add(mission)
    await db.commit()
    await db.refresh(mission)
    return mission


@router.get("", response_model=PaginatedOutboundMissions)
async def list_missions(
    workspace_id: uuid.UUID,
    current_user: CurrentUser,
    db: DB,
    workspace: Annotated[Workspace, Depends(get_workspace)],
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=100),
    status_filter: MissionStatus | None = Query(default=None, alias="status"),
    objective: str | None = Query(default=None, max_length=50),
    search: str | None = Query(default=None, max_length=255),
) -> PaginatedOutboundMissions:
    """List outbound missions in a workspace with optional filters."""
    query = apply_workspace_scope(select(OutboundMission), OutboundMission, workspace_id)

    if status_filter is not None:
        query = query.where(OutboundMission.status == status_filter)
    if objective is not None:
        query = query.where(OutboundMission.objective == objective)
    if search:
        like = f"%{search}%"
        query = query.where(OutboundMission.name.ilike(like))

    query = query.order_by(OutboundMission.updated_at.desc())
    result = await paginate(db, query, page=page, page_size=page_size)
    return PaginatedOutboundMissions(**result.to_response(OutboundMissionResponse))


@router.get("/{mission_id}", response_model=OutboundMissionResponse)
async def get_mission(
    workspace_id: uuid.UUID,
    mission_id: uuid.UUID,
    current_user: CurrentUser,
    db: DB,
    workspace: Annotated[Workspace, Depends(get_workspace)],
) -> OutboundMission:
    """Fetch a single outbound mission."""
    return await _get_mission_or_404(db, mission_id, workspace_id)


@router.put("/{mission_id}", response_model=OutboundMissionResponse)
@router.patch("/{mission_id}", response_model=OutboundMissionResponse)
async def update_mission(
    workspace_id: uuid.UUID,
    mission_id: uuid.UUID,
    mission_in: OutboundMissionUpdate,
    current_user: CurrentUser,
    db: DB,
    workspace: Annotated[Workspace, Depends(get_workspace)],
) -> OutboundMission:
    """Partially update an outbound mission.

    Field updates are only allowed when the mission is in DRAFT, PAUSED, or
    ARCHIVED status. The ``status`` field is intentionally read-only here —
    callers must use the dedicated lifecycle endpoints (start/pause/resume/
    complete/archive).
    """
    mission = await _get_mission_or_404(db, mission_id, workspace_id)

    if mission.status not in _MUTABLE_STATUSES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                "Cannot edit an active or completed mission; "
                "pause or archive it first."
            ),
        )

    update_data = mission_in.model_dump(exclude_unset=True)
    # Status transitions go through dedicated endpoints.
    update_data.pop("status", None)

    await _validate_mission_fks(
        db,
        workspace_id,
        offer_id=update_data.get("offer_id"),
        default_agent_id=update_data.get("default_agent_id"),
        default_sequence_id=update_data.get("default_sequence_id"),
    )

    for field, value in update_data.items():
        setattr(mission, field, value)

    await db.commit()
    await db.refresh(mission)
    return mission


@router.delete("/{mission_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_mission(
    workspace_id: uuid.UUID,
    mission_id: uuid.UUID,
    current_user: CurrentUser,
    db: DB,
    workspace: Annotated[Workspace, Depends(get_workspace)],
) -> None:
    """Delete a mission.

    Only DRAFT or ARCHIVED missions can be deleted outright. Active or paused
    missions must be archived first (via ``POST /{id}/archive``) — this
    preserves the audit trail of any prospects/sequence enrollments that
    referenced the mission.
    """
    mission = await _get_mission_or_404(db, mission_id, workspace_id)

    if mission.status not in {MissionStatus.DRAFT, MissionStatus.ARCHIVED}:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Only draft or archived missions can be deleted; archive first.",
        )

    await db.delete(mission)
    await db.commit()


@router.post("/{mission_id}/start", response_model=OutboundMissionResponse)
async def start_mission(
    workspace_id: uuid.UUID,
    mission_id: uuid.UUID,
    current_user: CurrentUser,
    db: DB,
    workspace: Annotated[Workspace, Depends(get_workspace)],
) -> OutboundMission:
    """Start (or resume) a mission — moves DRAFT/PAUSED → ACTIVE."""
    mission = await _get_mission_or_404(db, mission_id, workspace_id)
    _transition_mission(
        mission,
        target=MissionStatus.ACTIVE,
        allowed_from=_STARTABLE_STATUSES,
        action="start",
    )
    await db.commit()
    await db.refresh(mission)
    return mission


@router.post("/{mission_id}/pause", response_model=OutboundMissionResponse)
async def pause_mission(
    workspace_id: uuid.UUID,
    mission_id: uuid.UUID,
    current_user: CurrentUser,
    db: DB,
    workspace: Annotated[Workspace, Depends(get_workspace)],
) -> OutboundMission:
    """Pause an active mission."""
    mission = await _get_mission_or_404(db, mission_id, workspace_id)
    _transition_mission(
        mission,
        target=MissionStatus.PAUSED,
        allowed_from=frozenset({MissionStatus.ACTIVE}),
        action="pause",
    )
    await db.commit()
    await db.refresh(mission)
    return mission


@router.post("/{mission_id}/resume", response_model=OutboundMissionResponse)
async def resume_mission(
    workspace_id: uuid.UUID,
    mission_id: uuid.UUID,
    current_user: CurrentUser,
    db: DB,
    workspace: Annotated[Workspace, Depends(get_workspace)],
) -> OutboundMission:
    """Resume a paused mission."""
    mission = await _get_mission_or_404(db, mission_id, workspace_id)
    _transition_mission(
        mission,
        target=MissionStatus.ACTIVE,
        allowed_from=frozenset({MissionStatus.PAUSED}),
        action="resume",
    )
    await db.commit()
    await db.refresh(mission)
    return mission


@router.post("/{mission_id}/complete", response_model=OutboundMissionResponse)
async def complete_mission(
    workspace_id: uuid.UUID,
    mission_id: uuid.UUID,
    current_user: CurrentUser,
    db: DB,
    workspace: Annotated[Workspace, Depends(get_workspace)],
) -> OutboundMission:
    """Mark a mission as completed."""
    mission = await _get_mission_or_404(db, mission_id, workspace_id)
    _transition_mission(
        mission,
        target=MissionStatus.COMPLETED,
        allowed_from=frozenset({MissionStatus.ACTIVE, MissionStatus.PAUSED}),
        action="complete",
    )
    await db.commit()
    await db.refresh(mission)
    return mission


@router.post("/{mission_id}/archive", response_model=OutboundMissionResponse)
async def archive_mission(
    workspace_id: uuid.UUID,
    mission_id: uuid.UUID,
    current_user: CurrentUser,
    db: DB,
    workspace: Annotated[Workspace, Depends(get_workspace)],
) -> OutboundMission:
    """Archive a mission (any state except already-archived)."""
    mission = await _get_mission_or_404(db, mission_id, workspace_id)
    _transition_mission(
        mission,
        target=MissionStatus.ARCHIVED,
        allowed_from=frozenset(
            {
                MissionStatus.DRAFT,
                MissionStatus.ACTIVE,
                MissionStatus.PAUSED,
                MissionStatus.COMPLETED,
            }
        ),
        action="archive",
    )
    await db.commit()
    await db.refresh(mission)
    return mission


# ---------------------------------------------------------------------------
# Mission stats
# ---------------------------------------------------------------------------


@router.get("/{mission_id}/stats", response_model=OutboundMissionStatsResponse)
async def get_mission_stats(
    workspace_id: uuid.UUID,
    mission_id: uuid.UUID,
    current_user: CurrentUser,
    db: DB,
    workspace: Annotated[Workspace, Depends(get_workspace)],
) -> OutboundMissionStatsResponse:
    """Return mission counters with derived reply / qualification / booking rates."""
    mission = await _get_mission_or_404(db, mission_id, workspace_id)
    return _stats_response(mission)


# ---------------------------------------------------------------------------
# Prospects
# ---------------------------------------------------------------------------


@router.get(
    "/{mission_id}/prospects",
    response_model=PaginatedLeadProspects,
)
async def list_mission_prospects(
    workspace_id: uuid.UUID,
    mission_id: uuid.UUID,
    current_user: CurrentUser,
    db: DB,
    workspace: Annotated[Workspace, Depends(get_workspace)],
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
    await _get_mission_or_404(db, mission_id, workspace_id)

    query = apply_workspace_scope(select(LeadProspect), LeadProspect, workspace_id).where(
        LeadProspect.mission_id == mission_id,
    )

    if status_filter is not None:
        query = query.where(LeadProspect.status == status_filter)
    if identity_kind is not None:
        query = query.where(LeadProspect.identity_kind == identity_kind)
    if source_type is not None:
        query = query.where(LeadProspect.source_type == source_type)
    if min_score is not None:
        query = query.where(LeadProspect.lead_score >= min_score)
    if max_score is not None:
        query = query.where(LeadProspect.lead_score <= max_score)
    if has_email is True:
        query = query.where(LeadProspect.email_hash.is_not(None))
    elif has_email is False:
        query = query.where(LeadProspect.email_hash.is_(None))
    if has_phone is True:
        query = query.where(LeadProspect.phone_hash.is_not(None))
    elif has_phone is False:
        query = query.where(LeadProspect.phone_hash.is_(None))
    if search:
        like = f"%{search}%"
        query = query.where(
            (LeadProspect.full_name.ilike(like))
            | (LeadProspect.company_name.ilike(like))
            | (LeadProspect.website_host.ilike(like))
        )

    query = query.order_by(
        LeadProspect.lead_score.desc(), LeadProspect.discovered_at.desc()
    )
    result = await paginate(db, query, page=page, page_size=page_size)
    return PaginatedLeadProspects(**result.to_response(LeadProspectResponse))


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
    workspace: Annotated[Workspace, Depends(get_workspace)],
) -> LeadProspect:
    """Fetch a single prospect that belongs to ``mission_id``."""
    return await _get_mission_prospect_or_404(db, mission_id, prospect_id, workspace_id)


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
    workspace: Annotated[Workspace, Depends(get_workspace)],
) -> LeadProspect:
    """Select a prospect for outreach — moves status to QUEUED."""
    prospect = await _get_mission_prospect_or_404(
        db, mission_id, prospect_id, workspace_id
    )

    if prospect.status in (ProspectStatus.SUPPRESSED, ProspectStatus.ARCHIVED):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Cannot select prospect in status '{prospect.status.value}'",
        )

    prospect.status = ProspectStatus.QUEUED
    await db.commit()
    await db.refresh(prospect)
    return prospect


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
    workspace: Annotated[Workspace, Depends(get_workspace)],
    reason: str | None = Query(default=None, max_length=255),
) -> LeadProspect:
    """Suppress a prospect (do-not-contact)."""
    prospect = await _get_mission_prospect_or_404(
        db, mission_id, prospect_id, workspace_id
    )

    prospect.status = ProspectStatus.SUPPRESSED
    prospect.suppression_reason = reason
    await db.commit()
    await db.refresh(prospect)
    return prospect


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
    workspace: Annotated[Workspace, Depends(get_workspace)],
    limit: int = Query(100, ge=1, le=500),
) -> list[LeadEnrichmentResultResponse]:
    """List enrichment audit rows for a single prospect (newest first)."""
    # Validates mission + prospect ownership before reading enrichment rows.
    await _get_mission_prospect_or_404(db, mission_id, prospect_id, workspace_id)

    query = (
        apply_workspace_scope(
            select(LeadEnrichmentResult),
            LeadEnrichmentResult,
            workspace_id,
        )
        .where(LeadEnrichmentResult.prospect_id == prospect_id)
        .order_by(LeadEnrichmentResult.created_at.desc())
        .limit(limit)
    )
    rows = (await db.execute(query)).scalars().all()
    return [LeadEnrichmentResultResponse.model_validate(r) for r in rows]


# ---------------------------------------------------------------------------
# Discovery jobs
# ---------------------------------------------------------------------------


@router.get(
    "/{mission_id}/discovery-jobs",
    response_model=PaginatedLeadDiscoveryJobs,
)
async def list_mission_discovery_jobs(
    workspace_id: uuid.UUID,
    mission_id: uuid.UUID,
    current_user: CurrentUser,
    db: DB,
    workspace: Annotated[Workspace, Depends(get_workspace)],
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=100),
    status_filter: DiscoveryJobStatus | None = Query(default=None, alias="status"),
    source_type: DiscoverySourceType | None = None,
) -> PaginatedLeadDiscoveryJobs:
    """List discovery jobs that emitted prospects into this mission."""
    await _get_mission_or_404(db, mission_id, workspace_id)

    query = apply_workspace_scope(
        select(LeadDiscoveryJob), LeadDiscoveryJob, workspace_id
    ).where(LeadDiscoveryJob.mission_id == mission_id)

    if status_filter is not None:
        query = query.where(LeadDiscoveryJob.status == status_filter)
    if source_type is not None:
        query = query.where(LeadDiscoveryJob.source_type == source_type)

    query = query.order_by(LeadDiscoveryJob.created_at.desc())
    result = await paginate(db, query, page=page, page_size=page_size)
    return PaginatedLeadDiscoveryJobs(**result.to_response(LeadDiscoveryJobResponse))


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
    workspace: Annotated[Workspace, Depends(get_workspace)],
) -> LeadDiscoveryJob:
    """Fetch a single discovery job."""
    await _get_mission_or_404(db, mission_id, workspace_id)
    job = await get_or_404(
        db,
        LeadDiscoveryJob,
        job_id,
        workspace_id=workspace_id,
        detail="Lead discovery job not found",
    )
    if job.mission_id != mission_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Lead discovery job not found",
        )
    return job


# ---------------------------------------------------------------------------
# Enrichment status aggregation
# ---------------------------------------------------------------------------


@router.get("/{mission_id}/enrichment-status")
async def get_mission_enrichment_status(
    workspace_id: uuid.UUID,
    mission_id: uuid.UUID,
    current_user: CurrentUser,
    db: DB,
    workspace: Annotated[Workspace, Depends(get_workspace)],
) -> dict[str, Any]:
    """Aggregate enrichment status for a mission.

    Returns counts grouped by ``(provider, status)`` plus totals for the
    prospect-level enrichment counters. Useful to drive a Lead Miner status
    panel without paginating the raw audit table.
    """
    mission = await _get_mission_or_404(db, mission_id, workspace_id)

    # Per-(provider, status) counts across this mission's enrichment audit rows.
    rows = (
        await db.execute(
            apply_workspace_scope(
                select(
                    LeadEnrichmentResult.provider,
                    LeadEnrichmentResult.status,
                    func.count(LeadEnrichmentResult.id),
                ),
                LeadEnrichmentResult,
                workspace_id,
            )
            .where(LeadEnrichmentResult.mission_id == mission_id)
            .group_by(LeadEnrichmentResult.provider, LeadEnrichmentResult.status)
        )
    ).all()

    by_provider: dict[str, dict[str, int]] = {}
    for provider, result_status, count in rows:
        provider_key = (
            provider.value if isinstance(provider, EnrichmentProvider) else str(provider)
        )
        status_key = (
            result_status.value
            if isinstance(result_status, EnrichmentResultStatus)
            else str(result_status)
        )
        by_provider.setdefault(provider_key, {})[status_key] = int(count)

    return {
        "mission_id": str(mission.id),
        "total_prospects_discovered": mission.total_prospects_discovered,
        "total_prospects_enriched": mission.total_prospects_enriched,
        "by_provider": by_provider,
    }


# ---------------------------------------------------------------------------
# Sequence overview + enrollments
# ---------------------------------------------------------------------------


@router.get("/{mission_id}/sequence")
async def get_mission_sequence_overview(
    workspace_id: uuid.UUID,
    mission_id: uuid.UUID,
    current_user: CurrentUser,
    db: DB,
    workspace: Annotated[Workspace, Depends(get_workspace)],
) -> dict[str, Any]:
    """Return the mission's default sequence + enrollment counters.

    Response shape::

        {
          "mission_id": "<uuid>",
          "default_sequence": OutboundSequenceResponse | null,
          "enrollment_counts": {"active": 3, "completed": 12, ...},
          "total_enrollments": 27
        }
    """
    mission = await _get_mission_or_404(db, mission_id, workspace_id)

    sequence_payload: dict[str, Any] | None = None
    if mission.default_sequence_id is not None:
        sequence_row = (
            await db.execute(
                apply_workspace_scope(
                    select(OutboundSequence).where(
                        OutboundSequence.id == mission.default_sequence_id
                    ),
                    OutboundSequence,
                    workspace_id,
                )
            )
        ).scalar_one_or_none()
        if sequence_row is not None:
            sequence_payload = OutboundSequenceResponse.model_validate(
                sequence_row
            ).model_dump(mode="json")

    enrollment_rows = (
        await db.execute(
            apply_workspace_scope(
                select(
                    OutboundSequenceEnrollment.status,
                    func.count(OutboundSequenceEnrollment.id),
                ),
                OutboundSequenceEnrollment,
                workspace_id,
            )
            .where(OutboundSequenceEnrollment.mission_id == mission_id)
            .group_by(OutboundSequenceEnrollment.status)
        )
    ).all()

    enrollment_counts: dict[str, int] = {}
    total_enrollments = 0
    for enrollment_status, count in enrollment_rows:
        key = (
            enrollment_status.value
            if isinstance(enrollment_status, SequenceEnrollmentStatus)
            else str(enrollment_status)
        )
        count_int = int(count)
        enrollment_counts[key] = count_int
        total_enrollments += count_int

    return {
        "mission_id": str(mission.id),
        "default_sequence": sequence_payload,
        "enrollment_counts": enrollment_counts,
        "total_enrollments": total_enrollments,
    }


@router.get(
    "/{mission_id}/enrollments",
    response_model=list[OutboundSequenceEnrollmentResponse],
)
async def list_mission_enrollments(
    workspace_id: uuid.UUID,
    mission_id: uuid.UUID,
    current_user: CurrentUser,
    db: DB,
    workspace: Annotated[Workspace, Depends(get_workspace)],
    status_filter: SequenceEnrollmentStatus | None = Query(default=None, alias="status"),
    limit: int = Query(100, ge=1, le=500),
) -> list[OutboundSequenceEnrollmentResponse]:
    """List sequence enrollments for the mission."""
    await _get_mission_or_404(db, mission_id, workspace_id)

    query = (
        apply_workspace_scope(
            select(OutboundSequenceEnrollment),
            OutboundSequenceEnrollment,
            workspace_id,
        )
        .where(OutboundSequenceEnrollment.mission_id == mission_id)
        .order_by(OutboundSequenceEnrollment.enrolled_at.desc())
        .limit(limit)
    )
    if status_filter is not None:
        query = query.where(OutboundSequenceEnrollment.status == status_filter)

    rows = (await db.execute(query)).scalars().all()
    return [OutboundSequenceEnrollmentResponse.model_validate(r) for r in rows]
