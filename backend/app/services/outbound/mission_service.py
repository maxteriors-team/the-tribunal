"""Outbound mission lifecycle and Lead Miner service logic."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from enum import Enum
from typing import Any

import structlog
from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.crud import get_or_404
from app.db.pagination import paginate
from app.db.scope import apply_workspace_scope
from app.models.agent import Agent
from app.models.lead_discovery_job import (
    DiscoveryJobStatus,
    DiscoverySourceType,
    LeadDiscoveryJob,
)
from app.models.lead_prospect import (
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
from app.services._filters import FilterSpec, apply_filter_specs, presence_filter, search_filter

logger = structlog.get_logger()

# Mission states that allow mutation (PUT and DELETE).
_MUTABLE_STATUSES: frozenset[MissionStatus] = frozenset(
    {MissionStatus.DRAFT, MissionStatus.PAUSED, MissionStatus.ARCHIVED}
)
# Mission states that can transition to ACTIVE via /start.
_STARTABLE_STATUSES: frozenset[MissionStatus] = frozenset(
    {MissionStatus.DRAFT, MissionStatus.PAUSED}
)
_DELETABLE_STATUSES: frozenset[MissionStatus] = frozenset(
    {MissionStatus.DRAFT, MissionStatus.ARCHIVED}
)
_MISSION_FILTER_SPECS: tuple[FilterSpec, ...] = (
    FilterSpec("status_filter", OutboundMission.status),
    FilterSpec("objective", OutboundMission.objective),
    FilterSpec("search", condition=search_filter(OutboundMission.name)),
)
_PROSPECT_FILTER_SPECS: tuple[FilterSpec, ...] = (
    FilterSpec("status_filter", LeadProspect.status),
    FilterSpec("identity_kind", LeadProspect.identity_kind),
    FilterSpec("source_type", LeadProspect.source_type),
    FilterSpec("min_score", LeadProspect.lead_score, "gte"),
    FilterSpec("max_score", LeadProspect.lead_score, "lte"),
    FilterSpec("has_email", condition=presence_filter(LeadProspect.email_hash)),
    FilterSpec("has_phone", condition=presence_filter(LeadProspect.phone_hash)),
    FilterSpec(
        "search",
        condition=search_filter(
            LeadProspect.full_name,
            LeadProspect.company_name,
            LeadProspect.website_host,
        ),
    ),
)
_DISCOVERY_JOB_FILTER_SPECS: tuple[FilterSpec, ...] = (
    FilterSpec("status_filter", LeadDiscoveryJob.status),
    FilterSpec("source_type", LeadDiscoveryJob.source_type),
)


def _enum_key(value: object) -> str:
    """Return a stable string key for enum or scalar aggregate values."""
    if isinstance(value, Enum):
        return str(value.value)
    return str(value)


class OutboundMissionService:
    """Service for outbound mission lifecycle, prospects, stats, and sequences."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self.log = logger.bind(service="outbound_mission")

    # ------------------------------------------------------------------
    # Workspace-scoped fetch and FK validation
    # ------------------------------------------------------------------

    async def ensure_workspace_scoped_fk(
        self,
        model: type[Agent | Offer | OutboundSequence],
        fk_id: uuid.UUID | None,
        workspace_id: uuid.UUID,
        label: str,
    ) -> None:
        """Validate that ``fk_id`` (if set) refers to a row owned by ``workspace_id``."""
        if fk_id is None:
            return
        result = await self.db.execute(
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

    async def validate_mission_fks(
        self,
        workspace_id: uuid.UUID,
        *,
        offer_id: uuid.UUID | None,
        default_agent_id: uuid.UUID | None,
        default_sequence_id: uuid.UUID | None,
    ) -> None:
        """Validate offer, agent, and sequence FKs against ``workspace_id``."""
        await self.ensure_workspace_scoped_fk(Offer, offer_id, workspace_id, "Offer")
        await self.ensure_workspace_scoped_fk(Agent, default_agent_id, workspace_id, "Agent")
        await self.ensure_workspace_scoped_fk(
            OutboundSequence,
            default_sequence_id,
            workspace_id,
            "Outbound sequence",
        )

    async def get_mission_or_404(
        self, mission_id: uuid.UUID, workspace_id: uuid.UUID
    ) -> OutboundMission:
        """Fetch a mission scoped to ``workspace_id`` or raise 404."""
        return await get_or_404(
            self.db,
            OutboundMission,
            mission_id,
            workspace_id=workspace_id,
            detail="Outbound mission not found",
        )

    async def get_mission_prospect_or_404(
        self,
        mission_id: uuid.UUID,
        prospect_id: uuid.UUID,
        workspace_id: uuid.UUID,
    ) -> LeadProspect:
        """Fetch a prospect that belongs to ``mission_id`` or raise 404."""
        await self.get_mission_or_404(mission_id, workspace_id)
        prospect = await get_or_404(
            self.db,
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

    # ------------------------------------------------------------------
    # Mission CRUD + lifecycle
    # ------------------------------------------------------------------

    async def create_mission(
        self,
        workspace_id: uuid.UUID,
        mission_in: OutboundMissionCreate,
        *,
        created_by_id: int | None,
    ) -> OutboundMission:
        """Create a new outbound mission in DRAFT status."""
        await self.validate_mission_fks(
            workspace_id,
            offer_id=mission_in.offer_id,
            default_agent_id=mission_in.default_agent_id,
            default_sequence_id=mission_in.default_sequence_id,
        )

        mission = OutboundMission(
            workspace_id=workspace_id,
            created_by_id=created_by_id,
            **mission_in.model_dump(),
        )
        self.db.add(mission)
        await self.db.commit()
        await self.db.refresh(mission)
        self.log.info(
            "outbound_mission_created",
            mission_id=str(mission.id),
            workspace_id=str(workspace_id),
        )
        return mission

    async def list_missions(
        self,
        workspace_id: uuid.UUID,
        *,
        page: int,
        page_size: int,
        status_filter: MissionStatus | None = None,
        objective: str | None = None,
        search: str | None = None,
    ) -> PaginatedOutboundMissions:
        """List outbound missions in a workspace with optional filters."""
        query = apply_workspace_scope(select(OutboundMission), OutboundMission, workspace_id)
        query = apply_filter_specs(
            query,
            _MISSION_FILTER_SPECS,
            {
                "status_filter": status_filter,
                "objective": objective,
                "search": search,
            },
        )

        query = query.order_by(OutboundMission.updated_at.desc())
        result = await paginate(self.db, query, page=page, page_size=page_size)
        return result.build_response(
            item_model=OutboundMissionResponse,
            response_builder=PaginatedOutboundMissions,
        )

    async def update_mission(
        self,
        workspace_id: uuid.UUID,
        mission_id: uuid.UUID,
        mission_in: OutboundMissionUpdate,
    ) -> OutboundMission:
        """Partially update a mutable outbound mission."""
        mission = await self.get_mission_or_404(mission_id, workspace_id)

        if mission.status not in _MUTABLE_STATUSES:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=("Cannot edit an active or completed mission; pause or archive it first."),
            )

        update_data = mission_in.model_dump(exclude_unset=True)
        # Status transitions go through dedicated endpoints.
        update_data.pop("status", None)

        await self.validate_mission_fks(
            workspace_id,
            offer_id=update_data.get("offer_id"),
            default_agent_id=update_data.get("default_agent_id"),
            default_sequence_id=update_data.get("default_sequence_id"),
        )

        for field, value in update_data.items():
            setattr(mission, field, value)

        await self.db.commit()
        await self.db.refresh(mission)
        return mission

    async def delete_mission(self, workspace_id: uuid.UUID, mission_id: uuid.UUID) -> None:
        """Delete a draft or archived mission."""
        mission = await self.get_mission_or_404(mission_id, workspace_id)

        if mission.status not in _DELETABLE_STATUSES:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Only draft or archived missions can be deleted; archive first.",
            )

        await self.db.delete(mission)
        await self.db.commit()

    async def start_mission(
        self, workspace_id: uuid.UUID, mission_id: uuid.UUID
    ) -> OutboundMission:
        """Start a mission by moving DRAFT/PAUSED to ACTIVE."""
        return await self.transition_mission(
            workspace_id,
            mission_id,
            target=MissionStatus.ACTIVE,
            allowed_from=_STARTABLE_STATUSES,
            action="start",
        )

    async def pause_mission(
        self, workspace_id: uuid.UUID, mission_id: uuid.UUID
    ) -> OutboundMission:
        """Pause an active mission."""
        return await self.transition_mission(
            workspace_id,
            mission_id,
            target=MissionStatus.PAUSED,
            allowed_from=frozenset({MissionStatus.ACTIVE}),
            action="pause",
        )

    async def resume_mission(
        self, workspace_id: uuid.UUID, mission_id: uuid.UUID
    ) -> OutboundMission:
        """Resume a paused mission."""
        return await self.transition_mission(
            workspace_id,
            mission_id,
            target=MissionStatus.ACTIVE,
            allowed_from=frozenset({MissionStatus.PAUSED}),
            action="resume",
        )

    async def complete_mission(
        self, workspace_id: uuid.UUID, mission_id: uuid.UUID
    ) -> OutboundMission:
        """Mark an active or paused mission as completed."""
        return await self.transition_mission(
            workspace_id,
            mission_id,
            target=MissionStatus.COMPLETED,
            allowed_from=frozenset({MissionStatus.ACTIVE, MissionStatus.PAUSED}),
            action="complete",
        )

    async def archive_mission(
        self, workspace_id: uuid.UUID, mission_id: uuid.UUID
    ) -> OutboundMission:
        """Archive a mission in any non-archived state."""
        return await self.transition_mission(
            workspace_id,
            mission_id,
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

    async def transition_mission(
        self,
        workspace_id: uuid.UUID,
        mission_id: uuid.UUID,
        *,
        target: MissionStatus,
        allowed_from: frozenset[MissionStatus],
        action: str,
    ) -> OutboundMission:
        """Apply a status transition with lifecycle-timestamp bookkeeping."""
        mission = await self.get_mission_or_404(mission_id, workspace_id)
        self.apply_transition(
            mission,
            target=target,
            allowed_from=allowed_from,
            action=action,
        )
        await self.db.commit()
        await self.db.refresh(mission)
        self.log.info(
            "outbound_mission_transitioned",
            mission_id=str(mission.id),
            workspace_id=str(workspace_id),
            action=action,
            status=target.value,
        )
        return mission

    def apply_transition(
        self,
        mission: OutboundMission,
        *,
        target: MissionStatus,
        allowed_from: frozenset[MissionStatus],
        action: str,
    ) -> None:
        """Mutate a mission status transition after validating the current state."""
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

    # ------------------------------------------------------------------
    # Mission stats
    # ------------------------------------------------------------------

    async def get_mission_stats(
        self, workspace_id: uuid.UUID, mission_id: uuid.UUID
    ) -> OutboundMissionStatsResponse:
        """Return mission counters with derived reply / qualification / booking rates."""
        mission = await self.get_mission_or_404(mission_id, workspace_id)
        return self.build_stats_response(mission)

    def build_stats_response(self, mission: OutboundMission) -> OutboundMissionStatsResponse:
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

    # ------------------------------------------------------------------
    # Prospects
    # ------------------------------------------------------------------

    async def list_mission_prospects(
        self,
        workspace_id: uuid.UUID,
        mission_id: uuid.UUID,
        *,
        page: int,
        page_size: int,
        status_filter: ProspectStatus | None = None,
        identity_kind: ProspectIdentityKind | None = None,
        source_type: str | None = None,
        min_score: int | None = None,
        max_score: int | None = None,
        has_email: bool | None = None,
        has_phone: bool | None = None,
        search: str | None = None,
    ) -> PaginatedLeadProspects:
        """List prospects belonging to a mission with filter + pagination."""
        await self.get_mission_or_404(mission_id, workspace_id)

        query = apply_workspace_scope(select(LeadProspect), LeadProspect, workspace_id).where(
            LeadProspect.mission_id == mission_id,
        )

        query = apply_filter_specs(
            query,
            _PROSPECT_FILTER_SPECS,
            {
                "status_filter": status_filter,
                "identity_kind": identity_kind,
                "source_type": source_type,
                "min_score": min_score,
                "max_score": max_score,
                "has_email": has_email,
                "has_phone": has_phone,
                "search": search,
            },
        )

        query = query.order_by(LeadProspect.lead_score.desc(), LeadProspect.discovered_at.desc())
        result = await paginate(self.db, query, page=page, page_size=page_size)
        return result.build_response(
            item_model=LeadProspectResponse,
            response_builder=PaginatedLeadProspects,
        )

    async def select_mission_prospect(
        self,
        workspace_id: uuid.UUID,
        mission_id: uuid.UUID,
        prospect_id: uuid.UUID,
    ) -> LeadProspect:
        """Select a prospect for outreach by moving it to QUEUED."""
        prospect = await self.get_mission_prospect_or_404(mission_id, prospect_id, workspace_id)

        if prospect.status in (ProspectStatus.SUPPRESSED, ProspectStatus.ARCHIVED):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Cannot select prospect in status '{prospect.status.value}'",
            )

        prospect.status = ProspectStatus.QUEUED
        await self.db.commit()
        await self.db.refresh(prospect)
        return prospect

    async def suppress_mission_prospect(
        self,
        workspace_id: uuid.UUID,
        mission_id: uuid.UUID,
        prospect_id: uuid.UUID,
        *,
        reason: str | None = None,
    ) -> LeadProspect:
        """Suppress a prospect as do-not-contact."""
        prospect = await self.get_mission_prospect_or_404(mission_id, prospect_id, workspace_id)

        prospect.status = ProspectStatus.SUPPRESSED
        prospect.suppression_reason = reason
        await self.db.commit()
        await self.db.refresh(prospect)
        return prospect

    async def list_prospect_enrichment_results(
        self,
        workspace_id: uuid.UUID,
        mission_id: uuid.UUID,
        prospect_id: uuid.UUID,
        *,
        limit: int,
    ) -> list[LeadEnrichmentResultResponse]:
        """List enrichment audit rows for a single prospect, newest first."""
        await self.get_mission_prospect_or_404(mission_id, prospect_id, workspace_id)

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
        rows = (await self.db.execute(query)).scalars().all()
        return [LeadEnrichmentResultResponse.model_validate(row) for row in rows]

    # ------------------------------------------------------------------
    # Discovery jobs
    # ------------------------------------------------------------------

    async def list_mission_discovery_jobs(
        self,
        workspace_id: uuid.UUID,
        mission_id: uuid.UUID,
        *,
        page: int,
        page_size: int,
        status_filter: DiscoveryJobStatus | None = None,
        source_type: DiscoverySourceType | None = None,
    ) -> PaginatedLeadDiscoveryJobs:
        """List discovery jobs that emitted prospects into this mission."""
        await self.get_mission_or_404(mission_id, workspace_id)

        query = apply_workspace_scope(
            select(LeadDiscoveryJob),
            LeadDiscoveryJob,
            workspace_id,
        ).where(LeadDiscoveryJob.mission_id == mission_id)

        query = apply_filter_specs(
            query,
            _DISCOVERY_JOB_FILTER_SPECS,
            {
                "status_filter": status_filter,
                "source_type": source_type,
            },
        )

        query = query.order_by(LeadDiscoveryJob.created_at.desc())
        result = await paginate(self.db, query, page=page, page_size=page_size)
        return result.build_response(
            item_model=LeadDiscoveryJobResponse,
            response_builder=PaginatedLeadDiscoveryJobs,
        )

    async def get_mission_discovery_job(
        self,
        workspace_id: uuid.UUID,
        mission_id: uuid.UUID,
        job_id: uuid.UUID,
    ) -> LeadDiscoveryJob:
        """Fetch a single discovery job that belongs to a mission."""
        await self.get_mission_or_404(mission_id, workspace_id)
        job = await get_or_404(
            self.db,
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

    # ------------------------------------------------------------------
    # Enrichment status aggregate
    # ------------------------------------------------------------------

    async def get_mission_enrichment_status(
        self, workspace_id: uuid.UUID, mission_id: uuid.UUID
    ) -> dict[str, Any]:
        """Aggregate enrichment status for a mission."""
        mission = await self.get_mission_or_404(mission_id, workspace_id)

        rows = (
            await self.db.execute(
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
            provider_key = _enum_key(provider)
            status_key = _enum_key(result_status)
            by_provider.setdefault(provider_key, {})[status_key] = int(count)

        return {
            "mission_id": str(mission.id),
            "total_prospects_discovered": mission.total_prospects_discovered,
            "total_prospects_enriched": mission.total_prospects_enriched,
            "by_provider": by_provider,
        }

    # ------------------------------------------------------------------
    # Sequence overview + enrollments
    # ------------------------------------------------------------------

    async def get_mission_sequence_overview(
        self, workspace_id: uuid.UUID, mission_id: uuid.UUID
    ) -> dict[str, Any]:
        """Return the mission's default sequence and enrollment counters."""
        mission = await self.get_mission_or_404(mission_id, workspace_id)

        sequence_payload: dict[str, Any] | None = None
        if mission.default_sequence_id is not None:
            sequence_row = (
                await self.db.execute(
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
                sequence_payload = OutboundSequenceResponse.model_validate(sequence_row).model_dump(
                    mode="json"
                )

        enrollment_rows = (
            await self.db.execute(
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
            count_int = int(count)
            enrollment_counts[_enum_key(enrollment_status)] = count_int
            total_enrollments += count_int

        return {
            "mission_id": str(mission.id),
            "default_sequence": sequence_payload,
            "enrollment_counts": enrollment_counts,
            "total_enrollments": total_enrollments,
        }

    async def list_mission_enrollments(
        self,
        workspace_id: uuid.UUID,
        mission_id: uuid.UUID,
        *,
        status_filter: SequenceEnrollmentStatus | None = None,
        limit: int,
    ) -> list[OutboundSequenceEnrollmentResponse]:
        """List sequence enrollments for the mission."""
        await self.get_mission_or_404(mission_id, workspace_id)

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

        rows = (await self.db.execute(query)).scalars().all()
        return [OutboundSequenceEnrollmentResponse.model_validate(row) for row in rows]
