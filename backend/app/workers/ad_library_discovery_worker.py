"""Ad-library discovery worker.

Polls pending ad-library :class:`LeadDiscoveryJob` rows (Meta / Google), runs
the selected provider, upserts advertisers + creatives, and computes the
"consistent but not testing" signal for each — closing the long-standing
"nothing actually executes a discovery job" gap for these sources.

Poll-based with ``with_for_update(skip_locked=True)`` so multiple replicas
never double-run a job, and a global hourly provider-call cap so re-scans +
multi-replica deploys stay under the Meta ~200/hr tier.
"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.db.session import AsyncSessionLocal
from app.models.lead_discovery_job import (
    DiscoveryJobStatus,
    DiscoverySourceType,
    LeadDiscoveryJob,
)
from app.services.ad_intelligence.discovery import run_discovery_job
from app.services.lead_discovery.errors import (
    LeadDiscoveryRateLimitError,
)
from app.workers.base import BaseWorker, WorkerRegistry

# Process a small batch per tick; provider calls are rate-limited globally.
MAX_JOBS_PER_TICK = 3

_AD_LIBRARY_SOURCES = (
    DiscoverySourceType.META_AD_LIBRARY,
    DiscoverySourceType.GOOGLE_ADS_TRANSPARENCY,
)


class AdLibraryDiscoveryWorker(BaseWorker):
    """Execute pending ad-library discovery jobs."""

    POLL_INTERVAL_SECONDS = getattr(settings, "ad_library_discovery_poll_interval", 15)
    COMPONENT_NAME = "ad_library_discovery_worker"
    MAX_CONCURRENCY = 1  # serialize provider calls to respect the hourly cap

    async def _process_items(self) -> None:
        async with AsyncSessionLocal() as db:
            jobs = await self._claim_jobs(db)
            if not jobs:
                return
            self.logger.debug("processing_ad_library_jobs", count=len(jobs))
            for job in jobs:
                await self._run_job(db, job)
            await db.commit()

    async def _claim_jobs(self, db: AsyncSession) -> list[LeadDiscoveryJob]:
        result = await db.execute(
            select(LeadDiscoveryJob)
            .where(
                LeadDiscoveryJob.status == DiscoveryJobStatus.PENDING,
                LeadDiscoveryJob.source_type.in_(_AD_LIBRARY_SOURCES),
            )
            .order_by(LeadDiscoveryJob.created_at)
            .limit(MAX_JOBS_PER_TICK)
            .with_for_update(skip_locked=True)
        )
        return list(result.scalars().all())

    async def _run_job(self, db: AsyncSession, job: LeadDiscoveryJob) -> None:
        log = self.logger.bind(job_id=str(job.id), workspace_id=str(job.workspace_id))
        try:
            await run_discovery_job(db, job)
            self.record_items_processed(1)
        except LeadDiscoveryRateLimitError as exc:
            # Leave the job pending; the next cycle retries when budget frees up.
            job.status = DiscoveryJobStatus.PENDING
            job.started_at = None
            job.last_error = str(exc)[:2000]
            log.warning("ad_library_job_rate_limited", error=str(exc))
        except Exception as exc:  # noqa: BLE001 - record failure, continue batch
            job.status = DiscoveryJobStatus.FAILED
            job.completed_at = datetime.now(UTC)
            job.error_count = (job.error_count or 0) + 1
            job.last_error = str(exc)[:2000]
            log.exception("ad_library_job_failed", error=str(exc))


_registry = WorkerRegistry(AdLibraryDiscoveryWorker)
start_ad_library_discovery_worker = _registry.start
stop_ad_library_discovery_worker = _registry.stop
get_ad_library_discovery_worker = _registry.get
