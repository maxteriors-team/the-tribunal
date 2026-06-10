"""Service layer for the Ad Library API.

Owns workspace-scoped ad-library operations: launching searches (which enqueue
a :class:`LeadDiscoveryJob` the discovery worker executes), reading job status,
listing/ranking tracked advertisers by ICP fit, advertiser detail, saved
monitors, and promotion. The router stays thin; this enforces workspace scoping
so no cross-tenant data leaks.
"""

from __future__ import annotations

import math
import uuid
from typing import Any

import structlog
from sqlalchemy import Select, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.ad_advertiser import AdAdvertiser, AdPlatform
from app.models.ad_creative import AdCreative
from app.models.lead_discovery_job import (
    DiscoveryJobStatus,
    DiscoverySourceType,
    LeadDiscoveryJob,
)
from app.models.lead_prospect import LeadProspect
from app.models.outbound_mission import MissionStatus, OutboundMission
from app.schemas.ad_advertiser import (
    AdAdvertiserDetail,
    AdAdvertiserResponse,
    AdSignalBreakdown,
    PaginatedAdAdvertisers,
)
from app.schemas.ad_creative import AdCreativeResponse
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
from app.services.ad_intelligence.errors import (
    AdLibraryNotFoundError,
)
from app.services.ad_intelligence.icp import IcpProfile, ranked_advertiser_query
from app.services.ad_intelligence.monitors import (
    AD_MONITOR_KEY,
    build_monitor_config,
    compute_next_run,
    monitor_config,
    monitor_to_response_dict,
)
from app.services.ad_intelligence.prospecting import generate_prospect_for_advertiser
from app.services.outbound.promotion import ProspectPromotionService

logger = structlog.get_logger()

_PLATFORM_TO_SOURCE = {
    "meta": DiscoverySourceType.META_AD_LIBRARY,
    "google": DiscoverySourceType.GOOGLE_ADS_TRANSPARENCY,
}


class AdLibraryService:
    """Workspace-scoped operations for the ad-library prospecting feature."""

    def __init__(self, db: AsyncSession) -> None:
        self._db = db
        self._logger = logger.bind(component="ad_library_service")

    # ------------------------------------------------------------------
    # Search + jobs
    # ------------------------------------------------------------------

    async def create_search_job(
        self,
        workspace_id: uuid.UUID,
        request: AdLibrarySearchRequest,
        *,
        requested_by_id: int | None = None,
    ) -> LeadDiscoveryJob:
        """Create a pending ad-library discovery job for the worker to run."""
        source_type = _PLATFORM_TO_SOURCE.get(
            request.platform.value, DiscoverySourceType.META_AD_LIBRARY
        )
        params = {
            "platform": request.platform.value,
            "country": request.country,
            "search_terms": request.search_terms,
            "page_id": request.page_id,
            "page_name": request.page_name,
            "ad_delivery_date_min": (
                request.ad_delivery_date_min.isoformat() if request.ad_delivery_date_min else None
            ),
            "ad_delivery_date_max": (
                request.ad_delivery_date_max.isoformat() if request.ad_delivery_date_max else None
            ),
            "sort_by": request.sort_by,
            "max_results": request.max_results,
            "use_thirdparty_fallback": request.use_thirdparty_fallback,
            "icp_thresholds": (
                request.icp_thresholds.model_dump(exclude_none=True)
                if request.icp_thresholds
                else None
            ),
        }
        job = LeadDiscoveryJob(
            workspace_id=workspace_id,
            mission_id=request.mission_id,
            requested_by_id=requested_by_id,
            source_type=source_type,
            source_label=request.search_terms or request.page_name or request.page_id,
            query=request.search_terms,
            params=params,
            status=DiscoveryJobStatus.PENDING,
            requested_count=request.max_results,
        )
        self._db.add(job)
        await self._db.commit()
        await self._db.refresh(job)
        self._logger.info(
            "ad_library_search_enqueued",
            workspace_id=str(workspace_id),
            job_id=str(job.id),
            platform=request.platform.value,
        )
        return job

    async def get_job(self, workspace_id: uuid.UUID, job_id: uuid.UUID) -> LeadDiscoveryJob:
        """Return a discovery job scoped to the workspace, or 404."""
        result = await self._db.execute(
            select(LeadDiscoveryJob).where(
                LeadDiscoveryJob.id == job_id,
                LeadDiscoveryJob.workspace_id == workspace_id,
            )
        )
        job = result.scalar_one_or_none()
        if job is None:
            raise AdLibraryNotFoundError(f"Discovery job {job_id} not found")
        return job

    # ------------------------------------------------------------------
    # Advertisers
    # ------------------------------------------------------------------

    async def list_advertisers(
        self,
        workspace_id: uuid.UUID,
        *,
        platform: AdPlatform | None = None,
        only_qualified: bool = False,
        contact_traced: bool | None = None,
        icp_overrides: dict[str, Any] | None = None,
        page: int = 1,
        page_size: int = 25,
    ) -> PaginatedAdAdvertisers:
        """Return advertisers ranked by ``opportunity_score`` (workspace-scoped).

        When ``only_qualified`` is set, the ICP inclusion floors + exclusion
        ceilings (which filter out prolific testers) are applied in SQL.
        """
        profile = IcpProfile.from_overrides(icp_overrides)
        stmt = ranked_advertiser_query(workspace_id, profile, only_qualified=only_qualified)
        if platform is not None:
            stmt = stmt.where(AdAdvertiser.platform == platform)
        if contact_traced is not None:
            stmt = stmt.where(AdAdvertiser.contact_traced.is_(contact_traced))

        total = await self._count(stmt)
        rows = await self._db.execute(stmt.limit(page_size).offset((page - 1) * page_size))
        advertisers = rows.scalars().all()
        return PaginatedAdAdvertisers(
            items=[AdAdvertiserResponse.model_validate(a) for a in advertisers],
            total=total,
            page=page,
            page_size=page_size,
            pages=self._page_count(total, page_size),
        )

    async def get_advertiser_detail(
        self, workspace_id: uuid.UUID, advertiser_id: uuid.UUID
    ) -> AdAdvertiserDetail:
        """Return one advertiser with creatives, signal breakdown, and contact."""
        advertiser = await self._advertiser_or_404(workspace_id, advertiser_id)

        creative_rows = await self._db.execute(
            select(AdCreative)
            .where(AdCreative.advertiser_id == advertiser.id)
            .order_by(AdCreative.ad_delivery_start_time.desc().nullslast())
        )
        creatives = creative_rows.scalars().all()

        breakdown = AdSignalBreakdown(
            opportunity_score=advertiser.opportunity_score,
            signal_window_days=advertiser.signal_window_days,
            total_ad_count=advertiser.total_ad_count,
            active_ad_count=advertiser.active_ad_count,
            distinct_creative_count=advertiser.distinct_creative_count,
            active_creative_count=advertiser.active_creative_count,
            longest_running_active_days=advertiser.longest_running_active_days,
            creative_refresh_rate=advertiser.creative_refresh_rate,
            continuity_score=advertiser.continuity_score,
            platform_spread=advertiser.platform_spread,
            media_mix=advertiser.media_mix,
            reasons=advertiser.reasons,
            example_creative=advertiser.example_creative,
            signals=advertiser.signals,
        )
        traced = await self._traced_contact(advertiser)

        # Build from the base response (which has no relationship fields) so
        # pydantic never probes ``advertiser.creatives`` and triggers an async
        # lazy-load; creatives are attached explicitly from the eager query.
        base = AdAdvertiserResponse.model_validate(advertiser)
        return AdAdvertiserDetail(
            **base.model_dump(),
            signals=advertiser.signals,
            provenance=advertiser.provenance,
            evidence=advertiser.evidence,
            creatives=[AdCreativeResponse.model_validate(c) for c in creatives],
            signal_breakdown=breakdown,
            traced_contact=traced,
        )

    async def _traced_contact(self, advertiser: AdAdvertiser) -> dict[str, Any] | None:
        """Return a non-PII view of the traced contact from the linked prospect."""
        if advertiser.prospect_id is None:
            return None
        prospect = await self._db.get(LeadProspect, advertiser.prospect_id)
        if prospect is None:
            return None
        return {
            "prospect_id": str(prospect.id),
            "company_name": prospect.company_name,
            "website_url": prospect.website_url,
            "linkedin_url": prospect.linkedin_url,
            "has_email": prospect.has_email,
            "has_phone": prospect.has_phone,
            "status": prospect.status.value,
            "contact_id": prospect.contact_id,
            "lead_score": prospect.lead_score,
        }

    # ------------------------------------------------------------------
    # Monitors (saved searches)
    # ------------------------------------------------------------------

    async def list_monitors(self, workspace_id: uuid.UUID) -> list[AdMonitorResponse]:
        """List saved ad-library monitors for the workspace."""
        result = await self._db.execute(
            select(OutboundMission)
            .where(
                OutboundMission.workspace_id == workspace_id,
                OutboundMission.discovery_config[AD_MONITOR_KEY].isnot(None),
            )
            .order_by(OutboundMission.created_at.desc())
        )
        return [
            AdMonitorResponse.model_validate(monitor_to_response_dict(m))
            for m in result.scalars().all()
        ]

    async def create_monitor(
        self,
        workspace_id: uuid.UUID,
        request: AdMonitorCreate,
        *,
        created_by_id: int | None = None,
    ) -> AdMonitorResponse:
        """Create a saved monitor (an OutboundMission carrying ad-monitor config)."""
        config = build_monitor_config(
            name=request.name,
            search=request.search.model_dump(mode="json"),
            icp_thresholds=request.icp_thresholds.model_dump(),
            schedule_interval_hours=request.schedule_interval_hours,
            is_active=request.is_active,
        )
        mission = OutboundMission(
            workspace_id=workspace_id,
            created_by_id=created_by_id,
            name=request.name,
            objective="book_call",
            status=MissionStatus.ACTIVE,
            discovery_config={AD_MONITOR_KEY: config},
            next_run_at=compute_next_run(request.schedule_interval_hours)
            if request.is_active
            else None,
        )
        self._db.add(mission)
        await self._db.commit()
        await self._db.refresh(mission)
        return AdMonitorResponse.model_validate(monitor_to_response_dict(mission))

    async def update_monitor(
        self,
        workspace_id: uuid.UUID,
        monitor_id: uuid.UUID,
        request: AdMonitorUpdate,
    ) -> AdMonitorResponse:
        """Patch a saved monitor's search / thresholds / schedule / active flag."""
        mission = await self._monitor_or_404(workspace_id, monitor_id)
        config = dict(monitor_config(mission) or {})
        if request.name is not None:
            config["name"] = request.name
        if request.search is not None:
            config["search"] = request.search.model_dump(mode="json")
        if request.icp_thresholds is not None:
            merged = dict(config.get("icp_thresholds") or {})
            merged.update(request.icp_thresholds.model_dump(exclude_none=True))
            config["icp_thresholds"] = merged
        if request.schedule_interval_hours is not None:
            config["schedule_interval_hours"] = request.schedule_interval_hours
        if request.is_active is not None:
            config["is_active"] = request.is_active

        mission.discovery_config = {**(mission.discovery_config or {}), AD_MONITOR_KEY: config}
        if request.name is not None:
            mission.name = request.name
        # Re-arm the schedule when (re)activated.
        if config.get("is_active"):
            interval = int(config.get("schedule_interval_hours") or 24)
            mission.next_run_at = mission.next_run_at or compute_next_run(interval)
        else:
            mission.next_run_at = None
        await self._db.commit()
        await self._db.refresh(mission)
        return AdMonitorResponse.model_validate(monitor_to_response_dict(mission))

    async def delete_monitor(self, workspace_id: uuid.UUID, monitor_id: uuid.UUID) -> None:
        """Delete a saved monitor."""
        mission = await self._monitor_or_404(workspace_id, monitor_id)
        await self._db.delete(mission)
        await self._db.commit()

    async def _monitor_or_404(
        self, workspace_id: uuid.UUID, monitor_id: uuid.UUID
    ) -> OutboundMission:
        result = await self._db.execute(
            select(OutboundMission).where(
                OutboundMission.id == monitor_id,
                OutboundMission.workspace_id == workspace_id,
                OutboundMission.discovery_config[AD_MONITOR_KEY].isnot(None),
            )
        )
        mission = result.scalar_one_or_none()
        if mission is None:
            raise AdLibraryNotFoundError(f"Monitor {monitor_id} not found")
        return mission

    # ------------------------------------------------------------------
    # Promotion
    # ------------------------------------------------------------------

    async def promote_advertiser(
        self,
        workspace_id: uuid.UUID,
        advertiser_id: uuid.UUID,
        request: AdvertiserPromoteRequest,
    ) -> AdvertiserPromoteResult:
        """Promote one advertiser: advertiser -> prospect -> contact."""
        advertiser = await self._advertiser_or_404(workspace_id, advertiser_id)
        result = await self._promote_one(advertiser, request)
        await self._db.commit()
        return result

    async def bulk_promote(
        self,
        workspace_id: uuid.UUID,
        request: AdvertiserBulkPromoteRequest,
    ) -> AdvertiserBulkPromoteResult:
        """Promote many advertisers at once (workspace-scoped)."""
        rows = await self._db.execute(
            select(AdAdvertiser).where(
                AdAdvertiser.workspace_id == workspace_id,
                AdAdvertiser.id.in_(request.advertiser_ids),
            )
        )
        advertisers = {a.id: a for a in rows.scalars().all()}
        single = AdvertiserPromoteRequest(
            mission_id=request.mission_id,
            enroll_in_sequence=request.enroll_in_sequence,
            sequence_id=request.sequence_id,
            create_opportunity=request.create_opportunity,
            extra_tags=request.extra_tags,
        )
        results: list[AdvertiserPromoteResult] = []
        for advertiser_id in request.advertiser_ids:
            advertiser = advertisers.get(advertiser_id)
            if advertiser is None:
                results.append(
                    AdvertiserPromoteResult(
                        advertiser_id=advertiser_id,
                        promoted=False,
                        skipped_reason="not_found",
                    )
                )
                continue
            results.append(await self._promote_one(advertiser, single))
        await self._db.commit()
        promoted = sum(1 for r in results if r.promoted)
        return AdvertiserBulkPromoteResult(
            results=results,
            promoted_count=promoted,
            skipped_count=len(results) - promoted,
        )

    async def _promote_one(
        self, advertiser: AdAdvertiser, request: AdvertiserPromoteRequest
    ) -> AdvertiserPromoteResult:
        prospect = await generate_prospect_for_advertiser(
            self._db, advertiser, mission_id=request.mission_id
        )
        promotion = ProspectPromotionService(self._db)
        outcome = await promotion.promote(
            prospect,
            create_opportunity=request.create_opportunity,
            extra_tags=request.extra_tags,
        )
        return AdvertiserPromoteResult(
            advertiser_id=advertiser.id,
            prospect_id=prospect.id,
            contact_id=outcome.contact_id,
            promoted=outcome.promoted,
            skipped_reason=outcome.skipped_reason,
        )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _page_count(total: int, page_size: int) -> int:
        return max(1, math.ceil(total / page_size)) if total else 0

    async def _advertiser_or_404(
        self, workspace_id: uuid.UUID, advertiser_id: uuid.UUID
    ) -> AdAdvertiser:
        result = await self._db.execute(
            select(AdAdvertiser).where(
                AdAdvertiser.id == advertiser_id,
                AdAdvertiser.workspace_id == workspace_id,
            )
        )
        advertiser = result.scalar_one_or_none()
        if advertiser is None:
            raise AdLibraryNotFoundError(f"Advertiser {advertiser_id} not found")
        return advertiser

    async def _count(self, stmt: Select[tuple[AdAdvertiser]]) -> int:
        result = await self._db.execute(
            select(func.count()).select_from(stmt.order_by(None).subquery())
        )
        return int(result.scalar_one())
