"""Advertiser -> LeadProspect generation.

Turns an ICP-qualified :class:`AdAdvertiser` into a
:class:`~app.models.lead_prospect.LeadProspect` so it flows into the existing
outbound rails (enrichment -> contact promotion -> sequences). The ad signal —
including the **specific ad we'd reference in outreach** — is copied onto the
prospect's ``evidence`` so messaging can be concrete ("saw your ad running
since March…") instead of generic.

Idempotent: an advertiser already linked to a prospect is returned as-is, and
prospects dedupe on ``(workspace_id, dedupe_key)`` (landing host when known,
otherwise a synthetic ad-library key) so re-scans don't create duplicates.
"""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.encryption import hash_value
from app.models.ad_advertiser import AdAdvertiser
from app.models.lead_prospect import LeadProspect, ProspectIdentityKind, ProspectStatus
from app.services.ad_intelligence.icp import IcpProfile, qualifies
from app.services.lead_discovery.dedupe import dedupe_key_for_website, extract_host

if TYPE_CHECKING:
    pass

logger = structlog.get_logger()

_ADLIB_FACET = "adlib"


def _synthetic_dedupe_key(platform: str, advertiser_key: str) -> str:
    """Deterministic dedupe key for an advertiser with no landing host."""
    return hash_value(f"{_ADLIB_FACET}:{platform}:{advertiser_key}")


def _build_evidence(advertiser: AdAdvertiser) -> list[dict[str, object]]:
    """Compose the outreach-ready ad-signal evidence for a prospect."""
    return [
        {
            "type": "ad_signal",
            "source": "ad_library",
            "platform": advertiser.platform.value,
            "opportunity_score": advertiser.opportunity_score,
            "longest_running_active_days": advertiser.longest_running_active_days,
            "distinct_creative_count": advertiser.distinct_creative_count,
            "active_creative_count": advertiser.active_creative_count,
            "creative_refresh_rate": advertiser.creative_refresh_rate,
            "continuity_score": advertiser.continuity_score,
            "media_mix": advertiser.media_mix,
            "reasons": advertiser.reasons,
            # The exact ad to name in outreach.
            "example_creative": advertiser.example_creative,
            "page_url": advertiser.page_url,
        }
    ]


async def generate_prospect_for_advertiser(
    db: AsyncSession,
    advertiser: AdAdvertiser,
    *,
    mission_id: uuid.UUID | None = None,
) -> LeadProspect:
    """Create (or return the existing) prospect for ``advertiser``.

    Links ``advertiser.prospect_id`` and stamps the ad-signal evidence. Flushes
    but does not commit.
    """
    if advertiser.prospect_id is not None:
        existing = await db.get(LeadProspect, advertiser.prospect_id)
        if existing is not None:
            return existing

    website_host = advertiser.website_host or extract_host(advertiser.website_url)
    dedupe_key = (
        dedupe_key_for_website(advertiser.website_url or website_host)
        if website_host
        else _synthetic_dedupe_key(advertiser.platform.value, advertiser.advertiser_key)
    )

    # Reuse an existing prospect with the same dedupe key (cross-source merge).
    found = await db.execute(
        select(LeadProspect).where(
            LeadProspect.workspace_id == advertiser.workspace_id,
            LeadProspect.dedupe_key == dedupe_key,
        )
    )
    prospect = found.scalar_one_or_none()

    evidence = _build_evidence(advertiser)
    provenance = {
        "source": "ad_library",
        "platform": advertiser.platform.value,
        "advertiser_key": advertiser.advertiser_key,
        "advertiser_name": advertiser.advertiser_name,
        "page_url": advertiser.page_url,
        "discovery_job_id": str(advertiser.discovery_job_id)
        if advertiser.discovery_job_id
        else None,
    }

    if prospect is None:
        identity_kind = ProspectIdentityKind.WEBSITE if website_host else ProspectIdentityKind.MULTI
        prospect = LeadProspect(
            workspace_id=advertiser.workspace_id,
            mission_id=mission_id,
            discovery_job_id=advertiser.discovery_job_id,
            identity_kind=identity_kind,
            company_name=advertiser.advertiser_name,
            website_url=advertiser.website_url,
            website_host=website_host,
            website_host_hash=hash_value(website_host) if website_host else None,
            country_code=advertiser.country_code,
            source_type=f"{advertiser.platform.value}_ad_library",
            source_external_id=advertiser.advertiser_key,
            dedupe_key=dedupe_key,
            provenance=provenance,
            evidence=evidence,
            lead_score=advertiser.opportunity_score,
            status=ProspectStatus.NEW,
        )
        db.add(prospect)
    else:
        # Merge the ad signal onto the pre-existing prospect.
        prospect.evidence = [*(prospect.evidence or []), *evidence]
        merged = dict(prospect.provenance or {})
        merged.setdefault("ad_library", provenance)
        prospect.provenance = merged
        prospect.lead_score = max(prospect.lead_score, advertiser.opportunity_score)
        prospect.company_name = prospect.company_name or advertiser.advertiser_name
        if mission_id and prospect.mission_id is None:
            prospect.mission_id = mission_id

    await db.flush()
    advertiser.prospect_id = prospect.id
    await db.flush()
    return prospect


async def generate_prospects_for_qualified(
    db: AsyncSession,
    *,
    workspace_id: uuid.UUID,
    profile: IcpProfile | None = None,
    mission_id: uuid.UUID | None = None,
    limit: int = 100,
) -> list[LeadProspect]:
    """Generate prospects for all ICP-qualified, not-yet-promoted advertisers."""
    resolved = profile or IcpProfile()
    rows = await db.execute(
        select(AdAdvertiser)
        .where(
            AdAdvertiser.workspace_id == workspace_id,
            AdAdvertiser.prospect_id.is_(None),
        )
        .order_by(AdAdvertiser.opportunity_score.desc())
        .limit(limit)
    )
    created: list[LeadProspect] = []
    for advertiser in rows.scalars().all():
        if not qualifies(advertiser, resolved).qualified:
            continue
        prospect = await generate_prospect_for_advertiser(db, advertiser, mission_id=mission_id)
        created.append(prospect)
    logger.info(
        "ad_library_prospects_generated",
        workspace_id=str(workspace_id),
        count=len(created),
    )
    return created
