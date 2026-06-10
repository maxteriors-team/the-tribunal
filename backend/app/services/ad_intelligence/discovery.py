"""End-to-end execution of one ad-library discovery job.

Shared by :class:`AdLibraryDiscoveryWorker` and the monitor worker. Given a
pending :class:`LeadDiscoveryJob`, it:

1. Builds the platform provider for the job's workspace (credentials resolved
   per-workspace, settings fallback).
2. Reserves a provider call slot (global hourly cap) before hitting the API.
3. Runs the search, upserts advertisers + creatives idempotently, and computes
   the "consistent but not testing" signal for each touched advertiser.
4. Updates the job's counters + lifecycle status.

The function commits nothing — the caller owns the transaction boundary.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime
from typing import Any

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.ad_advertiser import AdAdvertiser
from app.models.ad_creative import AdCreative
from app.models.lead_discovery_job import DiscoveryJobStatus, LeadDiscoveryJob
from app.services.ad_intelligence.ad_store import AdStore
from app.services.ad_intelligence.provider_factory import build_provider
from app.services.ad_intelligence.rate_limit import (
    acquire_provider_call_slot,
    record_cost,
)
from app.services.ad_intelligence.signals import compute_signals_for_advertiser
from app.services.ad_intelligence.types import AdSearchRequest
from app.services.lead_discovery.errors import (
    LeadDiscoveryRateLimitError,
)

logger = structlog.get_logger()

# Map the discovery source type to the ad platform.
_SOURCE_TO_PLATFORM = {
    "meta_ad_library": "meta",
    "google_ads_transparency": "google",
}


@dataclass(slots=True)
class DiscoveryOutcome:
    """Result of running one discovery job."""

    advertiser_count: int
    ad_count: int
    qualified_count: int
    warnings: list[str]


def _parse_date(value: Any) -> date | None:
    if not value:
        return None
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value))
    except ValueError:
        return None


def search_request_from_job(job: LeadDiscoveryJob) -> AdSearchRequest:
    """Build an :class:`AdSearchRequest` from a discovery job's params."""
    params = job.params or {}
    platform = _SOURCE_TO_PLATFORM.get(str(job.source_type), "meta")
    return AdSearchRequest(
        platform=platform,
        country=str(params.get("country") or "US"),
        search_terms=params.get("search_terms") or job.query,
        page_id=params.get("page_id"),
        page_name=params.get("page_name"),
        ad_delivery_date_min=_parse_date(params.get("ad_delivery_date_min")),
        ad_delivery_date_max=_parse_date(params.get("ad_delivery_date_max")),
        sort_by=str(params.get("sort_by") or "longest_running"),
        max_results=int(params.get("max_results") or job.requested_count or 50),
        params={},
    )


async def run_discovery_job(db: AsyncSession, job: LeadDiscoveryJob) -> DiscoveryOutcome:
    """Execute ``job`` against its provider and persist results + signals.

    Mutates ``job`` (status, counters, timing). Raises on hard provider
    failures so the caller can record ``failed`` + retry; rate-limit errors are
    re-raised so the worker can leave the job ``pending`` for the next cycle.
    """
    log = logger.bind(
        component="ad_discovery",
        job_id=str(job.id),
        workspace_id=str(job.workspace_id),
    )
    request = search_request_from_job(job)
    params = job.params or {}
    use_thirdparty = bool(params.get("use_thirdparty_fallback"))

    job.status = DiscoveryJobStatus.RUNNING
    job.started_at = job.started_at or datetime.now(UTC)

    # Reserve a provider call slot under the global hourly cap before any I/O.
    allowed, _used = await acquire_provider_call_slot(request.platform)
    if not allowed:
        raise LeadDiscoveryRateLimitError(
            f"Ad-library hourly call cap reached for platform '{request.platform}'"
        )

    provider = await build_provider(
        db,
        workspace_id=job.workspace_id,
        platform=request.platform,
        use_thirdparty=use_thirdparty,
    )
    try:
        result = await provider.search(request)
    finally:
        await provider.close()

    # Meter the spent call for ops visibility (best-effort, non-blocking).
    await record_cost(request.platform)

    store = AdStore(db)
    advertisers = await store.upsert_result(
        workspace_id=job.workspace_id,
        result=result,
        discovery_job_id=job.id,
    )

    qualified = 0
    for advertiser in advertisers:
        creatives = await _load_creatives(db, advertiser)
        bundle = compute_signals_for_advertiser(advertiser, creatives)
        if bundle.opportunity_score >= 50:
            qualified += 1
    await db.flush()

    warnings = [w.message for w in result.warnings]
    job.discovered_count = result.advertiser_count
    job.duplicate_count = 0
    job.status = DiscoveryJobStatus.SUCCEEDED
    job.completed_at = datetime.now(UTC)
    if warnings:
        job.last_error = "; ".join(warnings)[:2000]

    log.info(
        "discovery_complete",
        advertisers=result.advertiser_count,
        ads=result.total_ad_count,
        qualified=qualified,
        warnings=len(warnings),
    )
    return DiscoveryOutcome(
        advertiser_count=result.advertiser_count,
        ad_count=result.total_ad_count,
        qualified_count=qualified,
        warnings=warnings,
    )


async def _load_creatives(db: AsyncSession, advertiser: AdAdvertiser) -> list[AdCreative]:
    rows = await db.execute(select(AdCreative).where(AdCreative.advertiser_id == advertiser.id))
    return list(rows.scalars().all())
