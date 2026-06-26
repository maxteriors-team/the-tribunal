"""Workspace-scoped people search + reveal + discovery launch.

Backs the ``/prospects`` router. Owns:

* :meth:`search_people` — the Apollo-style filtered, signal-joined, score-ranked
  query over person prospects.
* :meth:`reveal_email` — on-demand pattern inference + verification.
* :meth:`launch_people_discovery` — enqueue a ``web_people`` discovery job.
* :meth:`add_to_mission` — bulk-attach selected prospects to a mission.

All reads/writes are constrained to ``workspace_id`` so nothing leaks across
tenants. Heavy crawling never happens here — discovery runs in the worker.
"""

from __future__ import annotations

import math
import uuid

import structlog
from sqlalchemy import Select, exists, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.encryption import hash_value
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
    ProspectStatus,
)
from app.models.outbound_mission import OutboundMission
from app.models.prospect_signal import ProspectSignal, ProspectSignalStatus
from app.schemas.prospect_search import (
    AddToMissionRequest,
    AddToMissionResponse,
    PeopleDiscoveryRequest,
    PeopleSearchRequest,
    PeopleSearchResponse,
    PersonResult,
    ProspectSignalResponse,
    RevealEmailResponse,
    RevealPhoneResponse,
)
from app.services.exceptions import NotFoundError, ValidationError
from app.services.lead_discovery.dedupe import extract_host
from app.services.lead_discovery.email_patterns import candidate_emails
from app.services.lead_discovery.email_verifier import (
    EmailVerificationStatus,
    verify_email,
)
from app.services.lead_discovery.phone_finder import find_phone_candidates
from app.services.scraping.website_scraper import WebsiteScraperService

logger = structlog.get_logger()


class ProspectSearchService:
    """Workspace-scoped people-search operations."""

    def __init__(self, db: AsyncSession) -> None:
        self._db = db
        self._logger = logger.bind(component="prospect_search_service")

    # ------------------------------------------------------------------
    # Search
    # ------------------------------------------------------------------

    async def search_people(
        self, workspace_id: uuid.UUID, request: PeopleSearchRequest
    ) -> PeopleSearchResponse:
        """Return a paginated, signal-filtered, score-ranked people list."""
        base = self._apply_filters(
            select(LeadProspect).where(LeadProspect.workspace_id == workspace_id),
            request,
        )

        count_stmt = select(func.count()).select_from(base.subquery())
        total = int((await self._db.execute(count_stmt)).scalar_one())

        rows_stmt = (
            base.order_by(LeadProspect.lead_score.desc(), LeadProspect.discovered_at.desc())
            .offset((request.page - 1) * request.page_size)
            .limit(request.page_size)
        )
        prospects = list((await self._db.execute(rows_stmt)).scalars().all())

        signals_by_prospect = await self._load_signals(workspace_id, [p.id for p in prospects])
        items = [self._to_person_result(p, signals_by_prospect.get(p.id, [])) for p in prospects]
        pages = math.ceil(total / request.page_size) if total else 0
        return PeopleSearchResponse(
            items=items,
            total=total,
            page=request.page,
            page_size=request.page_size,
            pages=pages,
        )

    def _apply_filters(  # noqa: PLR0912 - flat filter chain, each branch trivial
        self, stmt: Select[tuple[LeadProspect]], request: PeopleSearchRequest
    ) -> Select[tuple[LeadProspect]]:
        # People only — must carry a personal name facet.
        stmt = stmt.where(
            or_(
                LeadProspect.full_name.isnot(None),
                LeadProspect.first_name.isnot(None),
                LeadProspect.last_name.isnot(None),
            )
        )

        if request.keywords:
            like = f"%{request.keywords.strip()}%"
            stmt = stmt.where(
                or_(
                    LeadProspect.full_name.ilike(like),
                    LeadProspect.title.ilike(like),
                    LeadProspect.company_name.ilike(like),
                )
            )
        if request.title:
            stmt = stmt.where(LeadProspect.title.ilike(f"%{request.title.strip()}%"))
        if request.seniority:
            stmt = stmt.where(
                or_(*[LeadProspect.title.ilike(f"%{term.strip()}%") for term in request.seniority])
            )
        if request.location:
            like = f"%{request.location.strip()}%"
            stmt = stmt.where(
                or_(
                    LeadProspect.location_label.ilike(like),
                    LeadProspect.city.ilike(like),
                    LeadProspect.region.ilike(like),
                )
            )
        if request.industry:
            # No dedicated industry column yet — match company / source query.
            like = f"%{request.industry.strip()}%"
            stmt = stmt.where(
                or_(
                    LeadProspect.company_name.ilike(like),
                    LeadProspect.source_query.ilike(like),
                )
            )
        if request.country_code:
            stmt = stmt.where(LeadProspect.country_code == request.country_code.upper())
        if request.has_email is True:
            stmt = stmt.where(LeadProspect.email_hash.isnot(None))
        elif request.has_email is False:
            stmt = stmt.where(LeadProspect.email_hash.is_(None))
        if request.has_phone is True:
            stmt = stmt.where(LeadProspect.phone_hash.isnot(None))
        elif request.has_phone is False:
            stmt = stmt.where(LeadProspect.phone_hash.is_(None))
        if request.min_score > 0:
            stmt = stmt.where(LeadProspect.lead_score >= request.min_score)
        if request.statuses:
            stmt = stmt.where(LeadProspect.status.in_(request.statuses))
        if request.mission_id is not None:
            stmt = stmt.where(LeadProspect.mission_id == request.mission_id)
        if request.signal_types:
            signal_match = exists(
                select(ProspectSignal.id).where(
                    ProspectSignal.prospect_id == LeadProspect.id,
                    ProspectSignal.signal_type.in_(request.signal_types),
                    ProspectSignal.strength >= request.min_signal_strength,
                    ProspectSignal.status == ProspectSignalStatus.ACTIVE,
                )
            )
            stmt = stmt.where(signal_match)
        elif request.min_signal_strength > 0:
            signal_match = exists(
                select(ProspectSignal.id).where(
                    ProspectSignal.prospect_id == LeadProspect.id,
                    ProspectSignal.strength >= request.min_signal_strength,
                    ProspectSignal.status == ProspectSignalStatus.ACTIVE,
                )
            )
            stmt = stmt.where(signal_match)
        return stmt

    async def _load_signals(
        self, workspace_id: uuid.UUID, prospect_ids: list[uuid.UUID]
    ) -> dict[uuid.UUID, list[ProspectSignal]]:
        if not prospect_ids:
            return {}
        rows = await self._db.execute(
            select(ProspectSignal)
            .where(
                ProspectSignal.workspace_id == workspace_id,
                ProspectSignal.prospect_id.in_(prospect_ids),
            )
            .order_by(ProspectSignal.strength.desc())
        )
        grouped: dict[uuid.UUID, list[ProspectSignal]] = {}
        for signal in rows.scalars().all():
            grouped.setdefault(signal.prospect_id, []).append(signal)
        return grouped

    @staticmethod
    def _to_person_result(prospect: LeadProspect, signals: list[ProspectSignal]) -> PersonResult:
        return PersonResult(
            id=prospect.id,
            workspace_id=prospect.workspace_id,
            mission_id=prospect.mission_id,
            contact_id=prospect.contact_id,
            first_name=prospect.first_name,
            last_name=prospect.last_name,
            full_name=prospect.full_name,
            title=prospect.title,
            email=prospect.email,
            phone_number=prospect.phone_number,
            has_email=prospect.has_email,
            has_phone=prospect.has_phone,
            company_name=prospect.company_name,
            website_url=prospect.website_url,
            website_host=prospect.website_host,
            linkedin_url=prospect.linkedin_url,
            country_code=prospect.country_code,
            region=prospect.region,
            city=prospect.city,
            location_label=prospect.location_label,
            source_type=prospect.source_type,
            lead_score=prospect.lead_score,
            status=prospect.status,
            provenance=prospect.provenance or {},
            discovered_at=prospect.discovered_at,
            signals=[ProspectSignalResponse.model_validate(s) for s in signals],
        )

    # ------------------------------------------------------------------
    # Reveal email
    # ------------------------------------------------------------------

    async def reveal_email(
        self, workspace_id: uuid.UUID, prospect_id: uuid.UUID
    ) -> RevealEmailResponse:
        """Infer + verify a person's email on demand. Persists the result."""
        prospect = await self._get_prospect_or_404(workspace_id, prospect_id)
        domain = prospect.website_host or extract_host(prospect.website_url)
        if not domain:
            raise ValidationError("Prospect has no company domain to infer an email from")

        candidates = candidate_emails(
            prospect.first_name,
            prospect.last_name,
            domain,
            full_name=prospect.full_name,
        )
        # Verify an already-stored guess first, else the top candidate.
        target_email = prospect.email if prospect.email_hash else None
        chosen_pattern: str | None = (prospect.provenance or {}).get("email_pattern")
        if target_email is None:
            if not candidates:
                raise ValidationError("Not enough identity to infer an email (need a name)")
            target_email = candidates[0].email
            chosen_pattern = candidates[0].pattern

        verification = await verify_email(target_email)
        if not prospect.email_hash:
            prospect.email = target_email
            prospect.email_hash = hash_value(target_email)
        is_verified = verification.status == EmailVerificationStatus.VERIFIED
        provenance = dict(prospect.provenance or {})
        provenance["email_status"] = "verified" if is_verified else verification.status.value
        provenance["email_pattern"] = chosen_pattern
        provenance["email_verification"] = {
            "status": verification.status.value,
            "confidence": verification.confidence,
            "checked_mx": verification.checked_mx,
            "checked_smtp": verification.checked_smtp,
        }
        prospect.provenance = provenance

        self._db.add(
            LeadEnrichmentResult(
                workspace_id=workspace_id,
                prospect_id=prospect.id,
                mission_id=prospect.mission_id,
                provider=EnrichmentProvider.EMAIL_LOOKUP,
                status=(
                    EnrichmentResultStatus.SUCCESS
                    if is_verified
                    else EnrichmentResultStatus.PARTIAL
                ),
                extracted={
                    "email": True,
                    "pattern": chosen_pattern,
                    "verification_status": verification.status.value,
                    "confidence": verification.confidence,
                },
                response_payload={"domain": domain, "source": "reveal_email"},
            )
        )
        await self._db.commit()
        return RevealEmailResponse(
            prospect_id=prospect.id,
            email=target_email,
            pattern=chosen_pattern,
            verification_status=verification.status.value,
            confidence=verification.confidence,
            candidates=[
                {"email": c.email, "pattern": c.pattern, "confidence": c.confidence}
                for c in candidates[:5]
            ],
        )

    # ------------------------------------------------------------------
    # Reveal phone
    # ------------------------------------------------------------------

    async def reveal_phone(
        self,
        workspace_id: uuid.UUID,
        prospect_id: uuid.UUID,
        *,
        scraper: WebsiteScraperService | None = None,
    ) -> RevealPhoneResponse:
        """Scrape a prospect's company site for a business line. Persists it.

        Phone numbers can't be inferred from a name, so this crawls the
        company's own first-party pages and attaches the best-ranked published
        number — a business / main line, not a personal direct dial. Only fills
        ``phone_number`` when the prospect has none (never overwrites).
        """
        prospect = await self._get_prospect_or_404(workspace_id, prospect_id)
        domain = prospect.website_host or extract_host(prospect.website_url)
        if not domain:
            raise ValidationError("Prospect has no company domain to find a phone from")

        if not settings.phone_reveal_enabled:
            return RevealPhoneResponse(
                prospect_id=prospect.id,
                phone_number=prospect.phone_number if prospect.phone_hash else None,
                source=(prospect.provenance or {}).get("phone_source"),
                candidates=[],
            )

        owns_scraper = scraper is None
        scraper = scraper or WebsiteScraperService()
        try:
            candidates = await find_phone_candidates(
                domain,
                scraper=scraper,
                max_pages=settings.phone_reveal_max_pages,
                country=(prospect.country_code or "US"),
            )
        finally:
            if owns_scraper:
                await scraper.close()

        chosen = candidates[0] if candidates else None
        found = chosen is not None
        # Persist only when the prospect has no phone yet — never overwrite.
        if chosen is not None and not prospect.phone_hash:
            prospect.phone_number = chosen.phone
            prospect.phone_hash = hash_value(chosen.phone)

        provenance = dict(prospect.provenance or {})
        provenance["phone_status"] = "found" if found else "not_found"
        if chosen is not None:
            provenance["phone_source"] = chosen.source
        provenance["phone_candidates"] = [
            {
                "phone": c.phone,
                "source": c.source,
                "confidence": c.confidence,
                "source_url": c.source_url,
            }
            for c in candidates[:5]
        ]
        prospect.provenance = provenance

        self._db.add(
            LeadEnrichmentResult(
                workspace_id=workspace_id,
                prospect_id=prospect.id,
                mission_id=prospect.mission_id,
                provider=EnrichmentProvider.PHONE_LOOKUP,
                status=(
                    EnrichmentResultStatus.SUCCESS if found else EnrichmentResultStatus.SKIPPED
                ),
                extracted={
                    "phone": found,
                    "source": chosen.source if chosen else None,
                    "confidence": chosen.confidence if chosen else 0,
                },
                response_payload={"domain": domain, "source": "reveal_phone"},
            )
        )
        await self._db.commit()
        return RevealPhoneResponse(
            prospect_id=prospect.id,
            phone_number=prospect.phone_number if prospect.phone_hash else None,
            source=chosen.source if chosen else None,
            candidates=[
                {"phone": c.phone, "source": c.source, "confidence": c.confidence}
                for c in candidates[:5]
            ],
        )

    # ------------------------------------------------------------------
    # Launch discovery
    # ------------------------------------------------------------------

    async def launch_people_discovery(
        self,
        workspace_id: uuid.UUID,
        request: PeopleDiscoveryRequest,
        *,
        requested_by_id: int | None = None,
    ) -> LeadDiscoveryJob:
        """Enqueue a ``web_people`` discovery job for the worker to run."""
        domains = [d for d in ([request.domain, *request.domains]) if d]
        if not domains and not (request.query and request.query.strip()):
            raise ValidationError("Provide a domain/domains or a query to search people")
        if request.mission_id is not None:
            await self._ensure_mission(workspace_id, request.mission_id)

        params: dict[str, object] = {
            "max_results": request.max_results,
            "location_label": request.location_label,
            "country_code": request.country_code,
            "region": request.region,
            "city": request.city,
        }
        if request.domain:
            params["domain"] = request.domain
        if request.domains:
            params["domains"] = request.domains

        job = LeadDiscoveryJob(
            workspace_id=workspace_id,
            mission_id=request.mission_id,
            requested_by_id=requested_by_id,
            source_type=DiscoverySourceType.WEB_PEOPLE,
            source_label=request.query or (domains[0] if domains else None),
            query=request.query,
            params=params,
            status=DiscoveryJobStatus.PENDING,
            requested_count=request.max_results,
        )
        self._db.add(job)
        await self._db.commit()
        await self._db.refresh(job)
        self._logger.info(
            "people_discovery_enqueued",
            workspace_id=str(workspace_id),
            job_id=str(job.id),
            domains=len(domains),
            has_query=bool(request.query),
        )
        return job

    # ------------------------------------------------------------------
    # Add to mission
    # ------------------------------------------------------------------

    async def add_to_mission(
        self, workspace_id: uuid.UUID, request: AddToMissionRequest
    ) -> AddToMissionResponse:
        """Attach the given prospects to ``mission_id``. Workspace-scoped."""
        await self._ensure_mission(workspace_id, request.mission_id)
        rows = await self._db.execute(
            select(LeadProspect).where(
                LeadProspect.workspace_id == workspace_id,
                LeadProspect.id.in_(request.prospect_ids),
            )
        )
        prospects = list(rows.scalars().all())
        added = 0
        skipped = 0
        for prospect in prospects:
            if prospect.mission_id == request.mission_id:
                skipped += 1
                continue
            prospect.mission_id = request.mission_id
            if prospect.status == ProspectStatus.SUPPRESSED:
                skipped += 1
                continue
            added += 1
        # Any requested id we didn't load (wrong workspace / missing) is skipped.
        skipped += len(request.prospect_ids) - len(prospects)
        await self._db.commit()
        self._logger.info(
            "prospects_added_to_mission",
            workspace_id=str(workspace_id),
            mission_id=str(request.mission_id),
            added=added,
            skipped=skipped,
        )
        return AddToMissionResponse(mission_id=request.mission_id, added=added, skipped=skipped)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    async def _get_prospect_or_404(
        self, workspace_id: uuid.UUID, prospect_id: uuid.UUID
    ) -> LeadProspect:
        row = await self._db.execute(
            select(LeadProspect).where(
                LeadProspect.workspace_id == workspace_id,
                LeadProspect.id == prospect_id,
            )
        )
        prospect = row.scalar_one_or_none()
        if prospect is None:
            raise NotFoundError("Lead prospect not found")
        return prospect

    async def _ensure_mission(
        self, workspace_id: uuid.UUID, mission_id: uuid.UUID
    ) -> OutboundMission:
        row = await self._db.execute(
            select(OutboundMission).where(
                OutboundMission.workspace_id == workspace_id,
                OutboundMission.id == mission_id,
            )
        )
        mission = row.scalar_one_or_none()
        if mission is None:
            raise NotFoundError("Outbound mission not found")
        return mission
